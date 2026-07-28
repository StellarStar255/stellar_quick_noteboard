"""Global (cross-notebook) search dialog (port of v1 show_global_search
L6340): frameless draggable card, live search entry, results list capped
at 300 across all notebooks, notebook name in accent + dimmed line preview
with the match highlighted. Clicking (or Enter on) a result emits
open_notebook_at(notebook, line_no, needle) and closes the dialog — the
main window switches and jumps (v1 _global_search_jump L6555).
"""

import html
import re

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem

from noteboard.core.theme import blend
from noteboard.ui.dialogs import StyledDialog

# v1's marker → 📎 substitution for result previews (L6407)
MARKER_SUB_RE = re.compile(
    r'\[(?:IMAGE|FILE):[^\]]+\]|\[/?(?:STRIKE|HL)(?::\w+)?\]')
MAX_RESULTS = 300          # v1 MAX_RESULTS
SEARCH_DEBOUNCE_MS = 250   # v1 schedule()


class GlobalSearchDialog(StyledDialog):

    #: (notebook, line_no [0-based content line], needle)
    open_notebook_at = Signal(str, int, str)

    def __init__(self, parent, tr, store, current_notebook,
                 current_content_provider, theme):
        super().__init__(parent, tr("global_search_title"))
        self._tr = tr
        self.store = store
        self.current_notebook = current_notebook
        self.current_content_provider = current_content_provider
        self.theme = theme
        self._results = []  # [(notebook, line_no, preview), ...]

        # Result count label next to the title (v1 count_lbl)
        self.count_label = QLabel("", self._header)
        self.count_label.setObjectName("dialogDim")
        self._header.layout().insertWidget(1, self.count_label)

        self.entry = QLineEdit(self._card)
        self.entry.setPlaceholderText(tr("global_search_hint"))
        self.body.addSpacing(10)
        self.body.addWidget(self.entry)
        self.body.addSpacing(8)

        self.listbox = QListWidget(self._card)
        self.listbox.setMinimumSize(640, 380)  # v1 680x480 card
        self.body.addWidget(self.listbox)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._timer.timeout.connect(self._do_search)
        self.entry.textChanged.connect(lambda *_: self._timer.start())
        self.entry.installEventFilter(self)
        self.listbox.itemClicked.connect(self._jump_item)
        self.entry.setFocus()

    # ── searching ────────────────────────────────────────────────────────

    def _notebook_content(self, nb):
        if nb == self.current_notebook and self.current_content_provider:
            # live editor state, not the possibly-stale file (v1 L6453)
            return self.current_content_provider()
        return self.store.load_note_text(nb)

    def _do_search(self):
        self._timer.stop()
        query = self.entry.text().strip()
        self._results = []
        self.listbox.clear()
        if not query:
            self.count_label.setText("")
            return
        q = query.lower()
        for nb in self.store.ordered_notebooks():
            try:
                content = self._notebook_content(nb)
            except Exception:
                continue
            for line_no, line in enumerate(content.split('\n')):
                p = line.lower().find(q)
                if p == -1:
                    continue
                snippet = line
                if len(snippet) > 100:  # v1 truncation around the match
                    s = max(0, p - 30)
                    snippet = (("…" if s else "")
                               + snippet[s:s + 100] + "…")
                preview = MARKER_SUB_RE.sub('📎', snippet).strip()
                self._results.append((nb, line_no, preview))
                if len(self._results) >= MAX_RESULTS:
                    break
            if len(self._results) >= MAX_RESULTS:
                break
        self.count_label.setText(
            self._tr("global_results_n").format(len(self._results)))
        self._render(q)

    def _render(self, q):
        for nb, line_no, preview in self._results:
            item = QListWidgetItem(self.listbox)
            item.setData(Qt.ItemDataRole.UserRole, (nb, line_no))
            label = QLabel(self._row_html(nb, preview, q), self.listbox)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setStyleSheet("background: transparent; padding: 3px;")
            item.setSizeHint(label.sizeHint())
            self.listbox.setItemWidget(item, label)
        if self._results:
            self.listbox.setCurrentRow(0)

    def _row_html(self, nb, preview, q):
        """Accent notebook name · dimmed preview, match tinted (v1 r_nb /
        r_dim / r_match tags)."""
        t = self.theme
        match_bg = blend(t["list_bg"], t["accent"], 0.38)
        body = ""
        pos = 0
        if q:
            lower = preview.lower()
            while True:
                j = lower.find(q, pos)
                if j == -1:
                    break
                body += html.escape(preview[pos:j])
                body += (f'<span style="background-color:{match_bg};'
                         f' color:{t["fg"]};">'
                         f'{html.escape(preview[j:j + len(q)])}</span>')
                pos = j + len(q)
        body += html.escape(preview[pos:])
        return (f'<span style="color:{t["accent"]}; font-weight:bold;">'
                f'{html.escape(nb)}</span>'
                f'<span style="color:{t["fg_dim"]};">&nbsp;·&nbsp;{body}'
                f'</span>')

    # ── jumping ──────────────────────────────────────────────────────────

    def _jump_item(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        nb, line_no = data
        needle = self.entry.text().strip()
        self.accept()
        self.open_notebook_at.emit(nb, line_no, needle)

    def _move_selection(self, delta):
        count = self.listbox.count()
        if not count:
            return
        self.listbox.setCurrentRow((self.listbox.currentRow() + delta)
                                   % count)

    def eventFilter(self, obj, event):
        if obj is self.entry and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Down:
                self._move_selection(1)
                return True
            if key == Qt.Key.Key_Up:
                self._move_selection(-1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.listbox.currentItem()
                if item is not None:
                    self._jump_item(item)
                return True
        return super().eventFilter(obj, event)
