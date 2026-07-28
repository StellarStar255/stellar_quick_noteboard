"""URL title previews (port of v1's url_preview model, QuickNoteBoard.py
~L9385-9556 + _fetch_url_title_async).

For every URL in the document, a dimmed "  {page title}" line is inserted
below the URL's block. Preview lines are EPHEMERAL: every fragment carries
PROP_EPHEMERAL (so MarkerDocument.serialize() drops the line with its
newline — never saved) plus PROP_URL_PREVIEW with the source URL (so the
manager can tell its own lines from image-name labels and remove orphans
when the URL disappears).

Titles come from core.urltitle.fetch_title on the QThreadPool; results are
cached in a dict owned by the app (NoteStore.load/save_url_title_cache).
Re-scans are debounced (the app calls schedule() from its contentsChanged
handler) and each scan is a diff: nothing is touched when the previews
already match the document.

Deviation from v1: Tk could insert previews with ``undo=False``; Qt's
QTextDocument cannot exclude an edit from the undo stack without clearing
it, so preview edits join the previous undo step instead (undoing a user
edit also undoes the preview adjustment it triggered).
"""

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextFormat

from noteboard.core import urltitle
from noteboard.core.markers import URL_RE
from noteboard.ui.editor.document import PROP_EPHEMERAL

#: str — the URL a preview line belongs to (marks manager-owned lines)
PROP_URL_PREVIEW = QTextFormat.UserProperty + 10

RESCAN_DEBOUNCE_MS = 1000  # re-scan 1s after the last edit


class _FetchSignals(QObject):
    finished = Signal(str, str)  # url, title ("" = failed)


class _FetchTask(QRunnable):
    """Thread-pool worker: fetch one URL title, report on the GUI thread."""

    def __init__(self, url, fetcher, emit):
        super().__init__()
        self._url = url
        self._fetcher = fetcher
        self._emit = emit

    def run(self):
        try:
            title = self._fetcher(self._url)
        except Exception:
            title = None
        try:
            self._emit(self._url, title or "")
        except RuntimeError:
            pass  # app quit while the fetch was in flight; signal source gone


class UrlPreviewManager(QObject):

    def __init__(self, marker_doc, cache=None, save_cache=None,
                 fetcher=urltitle.fetch_title, pool=None, parent=None):
        super().__init__(parent)
        self.marker_doc = marker_doc
        self.cache = cache if cache is not None else {}
        self.save_cache = save_cache      # callable(cache dict) or None
        self.fetcher = fetcher
        self.fetch_enabled = fetcher is not None
        #: True while the manager itself edits the document — the app's
        #: contentsChanged handler must ignore those changes.
        self.applying = False
        self._pending = set()
        self._pool = pool or QThreadPool.globalInstance()
        self._signals = _FetchSignals(self)
        self._signals.finished.connect(self._on_title_fetched)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RESCAN_DEBOUNCE_MS)
        self._timer.timeout.connect(self.rescan)

    def schedule(self):
        """Debounced rescan (call on every real document edit)."""
        self._timer.start()

    # ── scanning ─────────────────────────────────────────────────────────

    def _classify(self, block):
        """("content", None) | ("preview", url) | ("ephemeral", None)."""
        saw = False
        url = None
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                saw = True
                cf = frag.charFormat()
                if not cf.hasProperty(PROP_EPHEMERAL):
                    return ("content", None)
                if url is None and cf.hasProperty(PROP_URL_PREVIEW):
                    url = cf.property(PROP_URL_PREVIEW)
            it += 1
        if not saw:
            return ("content", None)  # empty line
        return ("preview", url) if url else ("ephemeral", None)

    def rescan(self):
        """Diff the document against the desired preview set: remove
        orphans, insert missing previews for cached titles, queue fetches
        for unknown URLs. No-op when everything already matches."""
        self._timer.stop()
        if self.applying:
            return
        doc = self.marker_doc.document
        ops = []      # ("del", start, end) / ("ins", pos, [(url, title)])
        fetch = []

        group_end = None    # insert position after the current content block
        group_urls = None   # its URLs, in order, deduped
        group_actual = []   # (url, del_start, del_end) previews following it

        def flush():
            if group_urls is None:
                return
            desired = [(u, self.cache[u]) for u in group_urls
                       if u in self.cache]
            if [u for u, _s, _e in group_actual] != [u for u, _t in desired]:
                for _u, s, e in group_actual:
                    ops.append(("del", s, e))
                if desired:
                    ops.append(("ins", group_end, desired))
            for u in group_urls:
                if u not in self.cache and u not in self._pending:
                    fetch.append(u)

        block = doc.begin()
        while block.isValid():
            kind, url = self._classify(block)
            if kind == "preview":
                s = block.position() - 1  # swallow the preceding newline
                e = block.position() + max(block.length() - 1, 0)
                if group_urls is not None:
                    group_actual.append((url, s, e))
                else:  # orphan with no content block before it
                    ops.append(("del", max(s, 0), e))
            elif kind == "content":
                flush()
                urls = []
                for m in URL_RE.finditer(block.text()):
                    if m.group(1) not in urls:
                        urls.append(m.group(1))
                group_end = block.position() + max(block.length() - 1, 0)
                group_urls = urls
                group_actual = []
            # "ephemeral" (image-name labels): transparent, keep walking
            block = block.next()
        flush()

        self._apply(ops)
        for url in fetch:
            if not self.fetch_enabled:
                continue
            self._pending.add(url)
            self._pool.start(_FetchTask(url, self.fetcher,
                                        self._signals.finished.emit))

    # ── document edits ───────────────────────────────────────────────────

    def _apply(self, ops):
        if not ops:
            return
        doc = self.marker_doc.document
        dim = self.marker_doc.theme["fg_dim"]
        was_modified = doc.isModified()
        self.applying = True
        # Deletions before insertions at the same position; back-to-front
        # so collected positions stay valid.
        ops.sort(key=lambda op: (op[1], 0 if op[0] == "ins" else 1),
                 reverse=True)
        cursor = QTextCursor(doc)
        cursor.joinPreviousEditBlock()  # keep previews out of their own
        try:                            # undo step (see module docstring)
            for op in ops:
                if op[0] == "del":
                    _kind, s, e = op
                    c = QTextCursor(doc)
                    c.setPosition(s)
                    c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
                    c.removeSelectedText()
                else:
                    _kind, pos, items = op
                    c = QTextCursor(doc)
                    c.setPosition(pos)
                    for url, title in items:
                        fmt = QTextCharFormat()
                        fmt.setProperty(PROP_EPHEMERAL, True)
                        fmt.setProperty(PROP_URL_PREVIEW, url)
                        fmt.setForeground(QColor(dim))
                        c.insertText("\n", QTextCharFormat())
                        c.insertText(f"  {title}", fmt)
        finally:
            cursor.endEditBlock()
            doc.setModified(was_modified)
            self.applying = False

    # ── async title fetching ─────────────────────────────────────────────

    def _on_title_fetched(self, url, title):
        self._pending.discard(url)
        if not title:
            return
        self.cache[url] = title
        if self.save_cache is not None:
            try:
                self.save_cache(self.cache)
            except Exception:
                pass  # cache write failure is non-fatal (v1)
        self.schedule()
