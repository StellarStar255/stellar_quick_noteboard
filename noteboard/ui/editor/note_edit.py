"""The note editor widget.

Thin QTextEdit over a MarkerDocument: it never sets char formats itself
(styling belongs to the highlighter, content to the document), it only
tracks the cursor's block so markers on the active line un-collapse.

M3 additions (ported from QuickNoteBoard.py):
- paste of clipboard bitmaps / files / plain text (handle_paste ~L7942,
  paste_image ~L8175, paste_files ~L8196) via insertFromMimeData;
- drag-edge image resize (get_image_resize_edge/on_image_* ~L8430-8556):
  25px edge threshold on right/top/bottom, 50-800 clamp keeping aspect,
  50ms throttle, whole drag = one undo step;
- image double-click opens the viewer (open_image_viewer ~L8558), file
  chips single-click select / double-click open (insert_file_link);
- object context menu: Open / Copy Path / Delete (full menu is M5/M6).

M5 additions (editing interactions):
- text context menu (show_text_context_menu L4929): cut/copy/paste,
  strikethrough toggle, highlight submenu, save-selection-as-notebook,
  copy-notebook-link; inapplicable items are grayed out, never hidden;
- highlight / strikethrough as marker-text edits (apply_highlight L5055,
  _toggle_line_highlight L5087, apply_strikethrough L5130): wrap with
  [HL:color]..[/HL] / [STRIKE]..[/STRIKE], one undo step each;
  Cmd/Ctrl+1..5 toggle the line highlight;
- task checkbox click toggles "- [ ]"/"- [x]" (_on_task_box_click L5523);
- [[notebook]] links and URLs open on Cmd/Ctrl/Alt+click (L5912, L9377);
- Tab/Shift+Tab multi-line indent/unindent (handle_tab L7862);
- cursor jump-over for ephemeral (never-serialized) lines.

M7 additions (platform integration):
- full v1 image/file object context menus (show_image_menu L8410,
  show_file_menu L8996): copy link / copy file / copy path / reveal /
  show original / open / delete, through ui.platform_utils; items that
  can't apply are grayed out, never hidden;
- copy: a selected object copies the real file + its [INTERNAL:...]
  marker (v1 handle_copy L7377); selections containing [STRIKE] copy
  rich text/html with <s> spans (v1 copy_with_strikethrough_rtf L7423);
- paste: an exact [INTERNAL:type:name] clipboard text re-inserts the
  object when the attachment exists in this notebook (v1
  paste_internal_link L8096), else falls through (file urls → import,
  otherwise plain text).

v2.0.0 parity addition (cross-notebook rich paste, v1 [INTERNAL:RICH:]
handle_copy ~L7370 / _insert_serialized_at_cursor ~L7185):
- copy of a selection containing image/file objects also sets RICH_MIME,
  a JSON {source_notebook, source_attachments_dir, markers};
- pasting it into a notebook with a different attachments dir copies the
  referenced files (and _thumb_ twins) over — internal names kept when
  free, else re-suffixed with the v1 timestamp+uuid scheme and the
  markers rewritten — and carries the filename-map entries; missing
  source files leave their marker as literal text instead of failing.
"""

import json
import os
import re
import shutil
import tempfile

from PySide6.QtCore import (QElapsedTimer, QMimeData, QPoint, QRectF, Qt,
                            QUrl, Signal)
from PySide6.QtGui import (QDesktopServices, QImage, QTextCharFormat,
                           QTextCursor)
from PySide6.QtWidgets import QApplication, QMenu, QTextEdit

from noteboard.core.attachments import generate_video_thumbnail, is_video_file
from noteboard.core.i18n import Translator
from noteboard.core.markers import (FILE_RE, HL_CLOSE, HL_OPEN_RE, IMAGE_RE,
                                    INTERNAL_LINK_RE, MARKER_SPLIT_RE,
                                    NOTEBOOK_LINK_RE, STRIKE_CLOSE,
                                    STRIKE_OPEN, TASK_RE, URL_RE,
                                    strip_markers, strip_style_markers)
from noteboard.core.theme import HIGHLIGHT_NAMES
from noteboard.ui import platform_utils
from noteboard.ui.editor import attachments_ui
from noteboard.ui.editor.document import (LINE_SEP, MAX_IMAGE_WIDTH,
                                          MIN_IMAGE_WIDTH, OBJECT_CHAR,
                                          PROP_EPHEMERAL, PROP_FILE_LINK,
                                          PROP_IMAGE_WIDTH,
                                          PROP_INTERNAL_NAME)
from noteboard.ui.editor.highlighter import _HL_MASK, _HL_SHIFT

EDGE_THRESHOLD = 25   # v1 get_image_resize_edge
EDGE_TOLERANCE = 10   # v1 in_x_range/in_y_range slack
MOTION_THROTTLE_MS = 50

# Style-marker tokens as they appear literally in the document text.
HL_TOKEN_RE = re.compile(r'\[HL:\w+\]|\[/HL\]')
STRIKE_TOKEN_RE = re.compile(r'\[STRIKE\]|\[/STRIKE\]')

# Private clipboard format carrying the raw selection marker text, so an
# in-board paste keeps full fidelity while external apps see the stripped
# plain/html payloads.
MARKER_MIME = "application/x-stellar-noteboard-markers"

# Private clipboard format for selections containing image/file objects:
# a small JSON {"source_notebook", "source_attachments_dir", "markers"}
# so a paste into ANOTHER notebook can copy the attachment files over
# (v1 wrapped the plain clipboard in [INTERNAL:RICH:notebook]... instead,
# handle_copy ~L7370 / _do_paste ~L7968).
RICH_MIME = "application/x-stellar-noteboard-rich"

_LINK_MODIFIERS = (Qt.KeyboardModifier.ControlModifier
                   | Qt.KeyboardModifier.MetaModifier
                   | Qt.KeyboardModifier.AltModifier)
_NAV_FORWARD = frozenset((Qt.Key.Key_Down, Qt.Key.Key_Right,
                          Qt.Key.Key_PageDown))
_NAV_BACKWARD = frozenset((Qt.Key.Key_Up, Qt.Key.Key_Left,
                           Qt.Key.Key_PageUp))


class _ObjectHit:
    """An image/file object char under the mouse."""

    __slots__ = ("position", "name", "key", "is_file", "rect")

    def __init__(self, position, name, key, is_file, rect):
        self.position = position
        self.name = name
        self.key = key
        self.is_file = is_file
        self.rect = rect  # QRectF in viewport coords


class NoteTextEdit(QTextEdit):

    #: selection's marker text, for the "save as new notebook" flow
    save_selection_as_notebook = Signal(str)
    #: [[notebook]] link activated with Cmd/Ctrl/Alt+click
    notebook_link_clicked = Signal(str)

    def __init__(self, marker_doc, highlighter, parent=None):
        super().__init__(parent)
        self.marker_doc = marker_doc
        self.highlighter = highlighter
        self.setDocument(marker_doc.document)
        self.setAcceptRichText(False)
        # App wiring (main_window overrides; defaults keep tests standalone)
        self.translator = Translator()
        self.notebook_name_provider = None  # callable() -> current nb name
        self._cursor_block = -1
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self._on_cursor_moved()

        # Image resize state (v1 image_resize_state)
        self.viewport().setMouseTracking(True)
        self._resize_state = None
        self._motion_timer = QElapsedTimer()
        self._motion_timer.start()
        self._viewers = []  # keep image viewer windows alive

    def _on_cursor_moved(self):
        block_no = self.textCursor().blockNumber()
        if block_no == self._cursor_block:
            return
        old = self._cursor_block
        self._cursor_block = block_no
        self.highlighter.cursor_block = block_no
        doc = self.document()
        if old >= 0:
            old_block = doc.findBlockByNumber(old)
            if old_block.isValid():
                self.highlighter.rehighlightBlock(old_block)
        new_block = doc.findBlockByNumber(block_no)
        if new_block.isValid():
            self.highlighter.rehighlightBlock(new_block)

    # ── paste (v1 handle_paste / paste_image / paste_files) ──────────────

    def insertFromMimeData(self, source):
        md = self.marker_doc
        if md.attachments_dir:
            # Cross-notebook rich paste: the private JSON payload names the
            # source attachments dir; when it differs from ours the
            # referenced files are copied over first (v1 RICH branch).
            if source.hasFormat(RICH_MIME) and self._paste_rich(source):
                return
            # Our own rich copy: raw marker text round-trips losslessly.
            if source.hasFormat(MARKER_MIME):
                data = bytes(source.data(MARKER_MIME)).decode("utf-8")
                self._insert_marker_text(data)
                return
            # Exact [INTERNAL:type:name] clipboard text (v1 _do_paste
            # L7991): re-insert the object when the attachment exists in
            # this notebook, else fall through (urls import / plain text).
            text = source.text().strip() if source.hasText() else ""
            m = INTERNAL_LINK_RE.match(text)
            if m and self._paste_internal_link(m.group(1), m.group(2)):
                return
            # Local files on the clipboard (Finder copy / drag-drop).
            if source.hasUrls():
                paths = [u.toLocalFile() for u in source.urls()
                         if u.isLocalFile()]
                paths = [p for p in paths if p and os.path.exists(p)]
                if paths:
                    self._paste_files(paths)
                    return
            # Raw bitmap (screenshot etc.) — like v1 handle_paste, only
            # when the clipboard has no usable text (~L8046).
            if source.hasImage() and not (source.hasText()
                                          and source.text().strip()):
                image = QImage(source.imageData())
                if not image.isNull():
                    self._paste_image(image)
                    return
        if source.hasText():
            self.insertPlainText(source.text())

    def _notify_saved(self, internal, original=None, path=None):
        saver = self.marker_doc.attachment_saver
        if saver is not None:
            saver(internal, original, path)

    def _paste_image(self, image):
        """v1 paste_image: save PNG under img_{ts}_{uuid}.png, insert the
        object + ephemeral name label + trailing newline."""
        md = self.marker_doc
        name = attachments_ui.save_pasted_image(image, md.attachments_dir)
        md.register_image(name, image)
        self._notify_saved(name)
        cursor = self.textCursor()
        cursor.beginEditBlock()
        if cursor.hasSelection():
            cursor.removeSelectedText()
        md.insert_image_at(cursor, name, with_label=True)
        cursor.insertText("\n", QTextCharFormat())
        cursor.endEditBlock()
        self.setTextCursor(cursor)

    def _paste_files(self, paths):
        """v1 paste_files: copy each into attachments under the v1 internal
        name, record the filename map, insert image/video/file objects.
        One edit block for the whole paste."""
        md = self.marker_doc
        cursor = self.textCursor()
        cursor.beginEditBlock()
        try:
            if cursor.hasSelection():
                cursor.removeSelectedText()
            for path in paths:
                try:
                    internal, original, abspath = attachments_ui.import_file(
                        path, md.attachments_dir)
                except OSError as e:
                    print(f"Error copying file {path}: {e}")
                    continue
                self._notify_saved(internal, original, abspath)
                ext = os.path.splitext(path)[1].lower()
                if ext in attachments_ui.IMAGE_EXTS and not os.path.isdir(path):
                    md.insert_image_at(cursor, internal, with_label=True)
                elif is_video_file(internal):
                    # Generate the thumbnail up front so insert_file_at can
                    # render it (v1 defers this; qlmanage is macOS-only and
                    # the chip fallback covers failure).
                    thumb = os.path.join(md.attachments_dir,
                                         f"_thumb_{internal}.png")
                    if not os.path.exists(thumb):
                        generate_video_thumbnail(
                            os.path.join(md.attachments_dir, internal), thumb)
                    md.insert_file_at(cursor, internal)
                else:
                    md.insert_file_at(cursor, internal)
                cursor.insertText("\n", QTextCharFormat())
        finally:
            cursor.endEditBlock()
        self.setTextCursor(cursor)

    def _attachment_exists(self, name):
        path = self.marker_doc.attachment_path(name)
        return bool(path and os.path.exists(path))

    def _paste_internal_link(self, link_type, name):
        """v1 paste_internal_link (L8096): insert the object for an
        [INTERNAL:image/file:name] marker when the attachment exists in
        the current notebook. Returns False to fall through otherwise."""
        if link_type not in ("image", "file"):
            return False
        if not self._attachment_exists(name):
            return False
        md = self.marker_doc
        cursor = self.textCursor()
        # v1 deselects (tag_remove SEL) rather than replacing the selection.
        cursor.clearSelection()
        cursor.beginEditBlock()
        try:
            if link_type == "image":
                md.insert_image_at(cursor, name, with_label=True)
            else:
                md.insert_file_at(cursor, name)
            cursor.insertText("\n", QTextCharFormat())
        finally:
            cursor.endEditBlock()
        self.setTextCursor(cursor)
        return True

    def _insert_marker_text(self, marker_text):
        """Insert marker text at the cursor: [IMAGE:]/[FILE:] markers whose
        attachment exists become objects, everything else stays literal
        text (the highlighter styles [STRIKE]/[HL:] as usual)."""
        md = self.marker_doc
        cursor = self.textCursor()
        cursor.beginEditBlock()
        try:
            if cursor.hasSelection():
                cursor.removeSelectedText()
            for part in MARKER_SPLIT_RE.split(marker_text):
                if not part:
                    continue
                m = IMAGE_RE.fullmatch(part)
                if m and self._attachment_exists(m.group(1)):
                    md.insert_image_at(cursor, m.group(1),
                                       int(m.group(2) or 0))
                    continue
                m = FILE_RE.fullmatch(part)
                if m and self._attachment_exists(m.group(1)):
                    md.insert_file_at(cursor, m.group(1))
                    continue
                cursor.insertText(part, QTextCharFormat())
        finally:
            cursor.endEditBlock()
        self.setTextCursor(cursor)

    # ── cross-notebook rich paste (v1 _insert_serialized_at_cursor) ──────

    def _paste_rich(self, source):
        """Paste our private JSON rich payload when it comes from ANOTHER
        notebook: copy each referenced attachment into this notebook
        (keeping internal names when free, else re-suffixing with the v1
        timestamp+uuid scheme and rewriting the marker), carry the
        filename-map entries, then insert through the marker paste path —
        one edit block, so undo removes the whole paste. Returns False to
        fall through (same notebook / malformed payload): the MARKER_MIME
        fast path handles the in-notebook case."""
        md = self.marker_doc
        try:
            payload = json.loads(bytes(source.data(RICH_MIME))
                                 .decode("utf-8"))
            markers = payload["markers"]
            src_dir = payload.get("source_attachments_dir")
        except (ValueError, KeyError, TypeError):
            return False
        if not isinstance(markers, str) or not markers or not src_dir:
            return False
        if os.path.realpath(src_dir) == os.path.realpath(md.attachments_dir):
            return False  # same notebook: keep the current fast path
        self._insert_marker_text(self._import_markers(markers, src_dir))
        return True

    def _import_markers(self, markers, src_dir):
        """Copy the [IMAGE:name(:w)]/[FILE:name] attachments referenced in
        *markers* from *src_dir* into this notebook's attachments dir,
        rewriting markers whose internal name had to change. A missing
        source file leaves its marker untouched (the paste inserts it
        as-is instead of failing — v1 ensure_file_in_target)."""
        md = self.marker_doc
        src_map = attachments_ui.load_filename_map(src_dir)
        targets = {}  # source internal name -> target name | None (missing)
        out = []
        for part in MARKER_SPLIT_RE.split(markers):
            if not part:
                continue
            m = IMAGE_RE.fullmatch(part) or FILE_RE.fullmatch(part)
            if m:
                name = m.group(1)
                if name not in targets:
                    try:
                        targets[name] = attachments_ui.copy_attachment_between(
                            src_dir, md.attachments_dir, name)
                    except OSError as e:
                        print(f"Error copying {name} from source "
                              f"notebook: {e}")
                        targets[name] = None
                    if targets[name] is not None:
                        self._carry_filename_map(src_map, name, targets[name])
                target = targets[name]
                if target is not None and target != name:
                    part = part.replace(name, target, 1)
            out.append(part)
        return "".join(out)

    def _carry_filename_map(self, src_map, src_name, target_name):
        """Merge the source notebook's filename-map entry under the target
        internal name so display names / original paths survive the paste
        (pasted screenshots carry no entry, as v1)."""
        info = src_map.get(src_name)
        if isinstance(info, dict):
            original, path = info.get("name"), info.get("path")
        else:
            original, path = info, None
        if not original:
            return
        self.marker_doc.filename_map[target_name] = {"name": original,
                                                     "path": path}
        self._notify_saved(target_name, original, path)

    # ── copy (v1 handle_copy / copy_with_strikethrough_rtf) ──────────────

    def createMimeDataFromSelection(self):
        """v1 handle_copy (L7280-7415): a selected image/file object
        copies the real file plus its [INTERNAL:...] marker text; a
        selection containing [STRIKE] copies rich text/html with <s>
        spans; anything else keeps the default Qt behavior. Selections
        containing image/file objects additionally carry the private JSON
        rich payload (RICH_MIME) so a paste into another notebook can copy
        the attachment files over — the plain-text fallback for those is
        the raw marker text (v1 put the [INTERNAL:RICH:...] wrapper on
        the plain clipboard)."""
        cursor = self.textCursor()
        if cursor.selectedText() == OBJECT_CHAR:
            cf = self._object_format_at(cursor.selectionStart())
            if cf is not None:
                name = cf.property(PROP_INTERNAL_NAME)
                kind = "file" if cf.property(PROP_FILE_LINK) else "image"
                marker = f"[INTERNAL:{kind}:{name}]"
                path = self.marker_doc.attachment_path(name)
                if path and os.path.exists(path):
                    mime = platform_utils.file_mime_data(path, text=marker)
                else:
                    mime = QMimeData()
                    mime.setText(marker)
                self._set_rich_payload(mime, self.selection_marker_text())
                return mime
        marker_text = self.selection_marker_text()
        has_objects = bool(IMAGE_RE.search(marker_text)
                           or FILE_RE.search(marker_text))
        if has_objects or STRIKE_OPEN in marker_text:
            mime = QMimeData()
            mime.setText(marker_text if has_objects
                         else strip_markers(marker_text))
            if STRIKE_OPEN in marker_text:
                mime.setHtml(platform_utils.strikethrough_html(marker_text))
            mime.setData(MARKER_MIME, marker_text.encode("utf-8"))
            if has_objects:
                self._set_rich_payload(mime, marker_text)
            return mime
        return super().createMimeDataFromSelection()

    def _set_rich_payload(self, mime, marker_text):
        """Attach the private JSON payload enabling cross-notebook
        attachment carry-over on paste."""
        md = self.marker_doc
        if not md.attachments_dir or not marker_text:
            return
        name = (self.notebook_name_provider()
                if self.notebook_name_provider else None)
        payload = {"source_notebook": name,
                   "source_attachments_dir":
                       os.path.abspath(md.attachments_dir),
                   "markers": marker_text}
        mime.setData(RICH_MIME,
                     json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    # ── object hit-testing ───────────────────────────────────────────────

    def _object_format_at(self, doc_pos):
        """Char format of the object char at *doc_pos*, or None."""
        doc = self.document()
        if doc_pos < 0 or doc.characterAt(doc_pos) != OBJECT_CHAR:
            return None
        probe = QTextCursor(doc)
        probe.setPosition(doc_pos + 1)
        cf = probe.charFormat()  # format of the char AT doc_pos
        if cf.isImageFormat() and cf.property(PROP_INTERNAL_NAME) is not None:
            return cf
        return None

    def _char_rect(self, doc_pos):
        """Viewport-coordinate rect of the char at *doc_pos*."""
        doc = self.document()
        block = doc.findBlock(doc_pos)
        if not block.isValid():
            return None
        layout = block.layout()
        if layout is None:
            return None
        rel = doc_pos - block.position()
        line = layout.lineForTextPosition(rel)
        if not line.isValid():
            return None
        x1 = line.cursorToX(rel)[0]
        x2 = line.cursorToX(rel + 1)[0]
        origin = layout.position()
        left = origin.x() + min(x1, x2) - self.horizontalScrollBar().value()
        top = origin.y() + line.y() - self.verticalScrollBar().value()
        return QRectF(left, top, abs(x2 - x1), line.height())

    def _hit_object(self, viewport_pos):
        """Find the image/file object char at/near *viewport_pos* (probes a
        little to the left too so the right resize edge stays reachable)."""
        candidates = []
        for probe_point in (viewport_pos,
                            viewport_pos - QPoint(EDGE_THRESHOLD, 0)):
            cur = self.cursorForPosition(probe_point)
            p = cur.position()
            for doc_pos in (p, p - 1):
                if doc_pos >= 0 and doc_pos not in candidates:
                    candidates.append(doc_pos)
        for doc_pos in candidates:
            cf = self._object_format_at(doc_pos)
            if cf is None:
                continue
            rect = self._char_rect(doc_pos)
            if rect is None:
                continue
            grown = rect.adjusted(-EDGE_TOLERANCE, -EDGE_TOLERANCE,
                                  EDGE_THRESHOLD + EDGE_TOLERANCE,
                                  EDGE_TOLERANCE)
            if not grown.contains(viewport_pos.x(), viewport_pos.y()):
                continue
            fmt = cf.toImageFormat()
            return _ObjectHit(doc_pos, cf.property(PROP_INTERNAL_NAME),
                              fmt.name(), bool(cf.property(PROP_FILE_LINK)),
                              rect)
        return None

    @staticmethod
    def _resize_edge(pos, rect):
        """Port of v1 get_image_resize_edge: closest of right/bottom/top
        within 25px, with 10px lateral tolerance; None otherwise."""
        dist_right = abs(pos.x() - rect.right())
        dist_bottom = abs(pos.y() - rect.bottom())
        dist_top = abs(pos.y() - rect.top())
        in_x = rect.left() - EDGE_TOLERANCE <= pos.x() <= \
            rect.right() + EDGE_TOLERANCE
        in_y = rect.top() - EDGE_TOLERANCE <= pos.y() <= \
            rect.bottom() + EDGE_TOLERANCE
        edges = []
        if in_y and dist_right <= EDGE_THRESHOLD:
            edges.append(('right', dist_right))
        if in_x and dist_bottom <= EDGE_THRESHOLD:
            edges.append(('bottom', dist_bottom))
        if in_x and dist_top <= EDGE_THRESHOLD:
            edges.append(('top', dist_top))
        if not edges:
            return None
        edges.sort(key=lambda e: e[1])
        return edges[0][0]

    # ── mouse events (resize / select / open) ────────────────────────────

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._resize_state is not None:
            if self._motion_timer.elapsed() >= MOTION_THROTTLE_MS:
                self._motion_timer.restart()
                self._apply_resize(pos)
            event.accept()
            return
        if self._motion_timer.elapsed() >= MOTION_THROTTLE_MS:
            self._motion_timer.restart()
            self._update_hover_cursor(pos)
        super().mouseMoveEvent(event)

    def _update_hover_cursor(self, pos):
        hit = self._hit_object(pos)
        shape = Qt.CursorShape.IBeamCursor
        if hit is not None:
            edge = None if hit.is_file else self._resize_edge(pos, hit.rect)
            if edge == 'right':
                shape = Qt.CursorShape.SizeHorCursor
            elif edge in ('top', 'bottom'):
                shape = Qt.CursorShape.SizeVerCursor
            elif hit.rect.contains(pos.x(), pos.y()):
                shape = Qt.CursorShape.PointingHandCursor
        elif self._interactive_span_at(pos):
            # task checkbox / URL / [[notebook]] link (v1 hand2 tag binds)
            shape = Qt.CursorShape.PointingHandCursor
        self.viewport().setCursor(shape)

    def _interactive_span_at(self, pos):
        """True when *pos* is over a task checkbox, URL or notebook link."""
        cursor = self.cursorForPosition(pos)
        col = cursor.positionInBlock()
        text = cursor.block().text()
        span = self._task_box_span(text)
        if span is not None and span[0] <= col <= span[1]:
            return True
        for regex in (URL_RE, NOTEBOOK_LINK_RE):
            for m in regex.finditer(text):
                if m.start() <= col <= m.end():
                    return True
        return False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if event.modifiers() & _LINK_MODIFIERS:
                if self._activate_link_at(pos):
                    event.accept()
                    return
            hit = self._hit_object(pos)
            if (hit is None
                    and event.modifiers() == Qt.KeyboardModifier.NoModifier
                    and self._toggle_task_at(pos)):
                event.accept()
                return
            if hit is not None:
                edge = (None if hit.is_file
                        else self._resize_edge(pos, hit.rect))
                if edge is not None:
                    # v1 on_image_press: start resize from the current size.
                    self._resize_state = {
                        'position': hit.position,
                        'start_x': pos.x(),
                        'start_y': pos.y(),
                        'start_width': max(1, int(hit.rect.width())),
                        'start_height': max(1, int(hit.rect.height())),
                        'edge': edge,
                        'first': True,
                        'last_width': None,
                    }
                    event.accept()
                    return
                if hit.rect.contains(pos.x(), pos.y()):
                    # Single-click: select the object char.
                    cursor = self.textCursor()
                    cursor.setPosition(hit.position)
                    cursor.setPosition(hit.position + 1,
                                       QTextCursor.MoveMode.KeepAnchor)
                    self.setTextCursor(cursor)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def _apply_resize(self, pos):
        """v1 on_image_drag: right edge tracks x; top/bottom track y and
        convert the height change back to a width, keeping aspect."""
        st = self._resize_state
        edge = st['edge']
        if edge == 'right':
            new_width = st['start_width'] + (pos.x() - st['start_x'])
        else:
            delta_y = (pos.y() - st['start_y'] if edge == 'bottom'
                       else st['start_y'] - pos.y())
            new_height = st['start_height'] + delta_y
            ratio = (new_height / st['start_height']
                     if st['start_height'] > 0 else 1)
            new_width = int(st['start_width'] * ratio)
        new_width = max(MIN_IMAGE_WIDTH, min(MAX_IMAGE_WIDTH, new_width))
        if new_width == st['last_width']:
            return
        # Whole drag collapses into a single undo step.
        if self.marker_doc.set_image_width(st['position'], new_width,
                                           join=not st['first']):
            st['first'] = False
            st['last_width'] = new_width

    def mouseReleaseEvent(self, event):
        if self._resize_state is not None:
            self._apply_resize(event.position().toPoint())
            self._resize_state = None
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        pos = event.position().toPoint()
        hit = self._hit_object(pos)
        if (hit is not None and event.button() == Qt.MouseButton.LeftButton
                and hit.rect.contains(pos.x(), pos.y())):
            self._open_object(hit)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _open_object(self, hit):
        path = self.marker_doc.attachment_path(hit.name)
        if not path or not os.path.exists(path):
            return
        if hit.is_file:
            # v1 open_file: hand off to the default application.
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            from noteboard.ui.image_viewer import ImageViewer
            viewer = ImageViewer(path,
                                 self.marker_doc.display_name(hit.name),
                                 theme=self.marker_doc.theme,
                                 parent=self.window())
            viewer.show()
            self._viewers.append(viewer)
            viewer.destroyed.connect(
                lambda *_: self._viewers.remove(viewer)
                if viewer in self._viewers else None)

    # ── links & task checkboxes ──────────────────────────────────────────

    def _activate_link_at(self, pos):
        """Cmd/Ctrl/Alt+click on a URL opens it (v1 L9377); on a
        [[notebook]] link emits notebook_link_clicked (v1 L5912)."""
        cursor = self.cursorForPosition(pos)
        col = cursor.positionInBlock()
        text = cursor.block().text()
        for m in URL_RE.finditer(text):
            if m.start() <= col <= m.end():
                QDesktopServices.openUrl(QUrl(m.group(1)))
                return True
        for m in NOTEBOOK_LINK_RE.finditer(text):
            if m.start() <= col <= m.end():
                self.notebook_link_clicked.emit(m.group(1))
                return True
        return False

    @staticmethod
    def _task_box_span(text):
        """(raw_start, raw_end, raw_state_pos, state_char) of a task box,
        looking through [HL:]/[STRIKE] wrappers — a highlighted task line
        is still a task line. None when the line is not a task."""
        stripped, imap = strip_style_markers(text)
        m = TASK_RE.match(stripped)
        if not m:
            return None
        if not imap:
            return None
        indent = len(m.group(1))
        start = imap[indent] if indent < len(imap) else 0
        end_idx = min(m.end(3), len(imap) - 1)
        return (start, imap[end_idx] + 1, imap[m.start(3)], m.group(3))

    def _toggle_task_at(self, pos):
        """Toggle a - [ ] / - [x] checkbox when its marker span is clicked
        (v1 _on_task_box_click L5577). One undo step."""
        cursor = self.cursorForPosition(pos)
        block = cursor.block()
        col = cursor.positionInBlock()
        span = self._task_box_span(block.text())
        if span is None:
            return False
        start, end, state_col, state_char = span
        if not (start <= col <= end):  # box span through ']'
            return False
        state_pos = block.position() + state_col
        new_state = ' ' if state_char in 'xX' else 'x'
        c = QTextCursor(self.document())
        c.setPosition(state_pos)
        c.setPosition(state_pos + 1, QTextCursor.MoveMode.KeepAnchor)
        c.beginEditBlock()
        c.insertText(new_state, QTextCharFormat())
        c.endEditBlock()
        return True

    # ── context menu / delete ────────────────────────────────────────────

    def contextMenuEvent(self, event):
        hit = self._hit_object(event.pos())
        if hit is not None and hit.rect.contains(event.pos().x(),
                                                 event.pos().y()):
            # Accepting the event here is the Qt equivalent of v1's
            # "break" fix: only ONE menu may show for a click.
            event.accept()
            menu = self.build_object_context_menu(hit)
            menu.exec(event.globalPos())
            return
        self._show_text_context_menu(event)

    def build_object_context_menu(self, hit):
        """v1 show_image_menu (L8410) / show_file_menu (L8996): stable
        structure — inapplicable items are grayed out, never hidden.
        Split from exec() so tests can inspect the menu."""
        tr = self.translator.tr
        name = hit.name
        path = self.marker_doc.attachment_path(name)
        exists = bool(path and os.path.exists(path))
        kind = "file" if hit.is_file else "image"

        menu = QMenu(self)
        menu.addAction(
            tr("copy_link"),
            lambda: platform_utils.copy_text(f"[INTERNAL:{kind}:{name}]"))
        menu.addSeparator()
        if hit.is_file:
            act = menu.addAction(
                tr("open_file"),
                lambda: platform_utils.open_with_default_app(path))
            act.setEnabled(exists)
            act = menu.addAction(tr("copy_file"),
                                 lambda: self._copy_file_object(name))
            act.setEnabled(exists)
        else:
            act = menu.addAction(tr("copy_img_file"),
                                 lambda: self._copy_file_object(name))
            act.setEnabled(exists)
        act = menu.addAction(
            tr("copy_file_path"),
            lambda: platform_utils.copy_text(os.path.abspath(path)))
        act.setEnabled(path is not None)  # standalone editor w/o dir
        act = menu.addAction(
            tr("show_in_finder"),
            lambda: platform_utils.reveal_in_file_manager(path))
        act.setEnabled(exists)
        act = menu.addAction(tr("show_original"),
                             lambda: self._reveal_original(name))
        act.setEnabled(bool(self._original_path(name)))
        if not hit.is_file:
            act = menu.addAction(
                tr("open_default"),
                lambda: platform_utils.open_with_default_app(path))
            act.setEnabled(exists)
        menu.addSeparator()
        menu.addAction(tr("delete"), lambda: self.delete_object_at(
            hit.position, hit.is_file))
        return menu

    def _copy_file_object(self, name):
        """v1 copy_file_to_clipboard (L9113): stage a temp copy under the
        original display name so external pastes keep it, then put the
        file on the clipboard."""
        md = self.marker_doc
        path = md.attachment_path(name)
        if not path or not os.path.exists(path):
            return
        staged = path
        display = md.display_name(name)
        try:
            temp_dir = tempfile.mkdtemp(prefix="sqn_clip_")
            staged = os.path.join(temp_dir, display)
            if os.path.isdir(path):
                shutil.copytree(path, staged)
            else:
                shutil.copy2(path, staged)
        except OSError as e:
            print(f"Error creating temp copy: {e}")
            staged = path  # fall back to the internal name
        platform_utils.copy_file_to_clipboard(staged)

    def _original_path(self, name):
        """v1 get_original_path (L4569): the pre-paste source path from
        the filename map; None when unrecorded (pasted screenshots)."""
        info = self.marker_doc.filename_map.get(name)
        if isinstance(info, dict):
            return info.get("path")
        return None

    def _reveal_original(self, name):
        """v1 reveal_original_file (L9263): reveal the original source
        file; when it moved/was deleted, open its folder if that still
        exists."""
        original = self._original_path(name)
        if not original:
            return
        if os.path.exists(original):
            platform_utils.reveal_in_file_manager(original)
            return
        folder = os.path.dirname(original)
        if os.path.isdir(folder):
            platform_utils.open_with_default_app(folder)
        else:
            print(f"Original file no longer exists: {original}")

    def _show_text_context_menu(self, event):
        event.accept()
        menu = self.build_text_context_menu(event.pos())
        menu.exec(event.globalPos())

    def build_text_context_menu(self, pos):
        """v1 show_text_context_menu (L4929): stable structure — items
        that don't apply are grayed out, never hidden. Split from the
        exec() call so tests can inspect the menu."""
        tr = self.translator.tr
        cursor = self.textCursor()
        has_sel = cursor.hasSelection()
        if not has_sel:
            # v1 places the cursor at the right-click position first.
            self.setTextCursor(self.cursorForPosition(pos))
            cursor = self.textCursor()

        menu = QMenu(self)

        # Clipboard: cut/copy need a selection, paste needs content
        act = menu.addAction(tr("ctx_cut"), self.cut)
        act.setEnabled(has_sel)
        act = menu.addAction(tr("ctx_copy"), self.copy)
        act.setEnabled(has_sel)
        md = QApplication.clipboard().mimeData()
        act = menu.addAction(tr("ctx_paste"), self.paste)
        act.setEnabled(bool(md and (md.hasText() or md.hasImage()
                                    or md.hasUrls())))
        menu.addSeparator()

        # Strikethrough toggle; label reflects the state at the selection
        has_strike = has_sel and self._strike_open_at(cursor.selectionStart())
        if has_strike:
            menu.addAction(tr("remove_strike"), self.remove_strikethrough)
        else:
            act = menu.addAction(tr("strikethrough"), self.apply_strikethrough)
            act.setEnabled(has_sel)
        menu.addSeparator()

        # Highlight submenu: 5 colors + remove
        hl_menu = menu.addMenu(tr("highlight_menu"))
        for color in HIGHLIGHT_NAMES:
            cmd = ((lambda c=color: self.apply_highlight(c)) if has_sel
                   else (lambda c=color: self.toggle_line_highlight(c)))
            hl_menu.addAction(tr(f"hl_{color}"), cmd)
        doc = self.document()
        first = doc.findBlock(cursor.selectionStart()).blockNumber()
        last = doc.findBlock(cursor.selectionEnd()).blockNumber()
        has_hl = any(self._line_has_any_highlight(doc.findBlockByNumber(n))
                     for n in range(first, last + 1))
        act = hl_menu.addAction(tr("remove_highlight"), self.remove_highlight)
        act.setEnabled(has_hl)
        menu.addSeparator()

        act = menu.addAction(tr("save_as_nb"), self._emit_save_selection)
        act.setEnabled(has_sel)
        act = menu.addAction(tr("copy_nb_link"), self.copy_notebook_link)
        act.setEnabled(self.notebook_name_provider is not None)
        return menu

    def _emit_save_selection(self):
        content = self.selection_marker_text()
        if content.strip():
            self.save_selection_as_notebook.emit(content)

    def copy_notebook_link(self):
        """v1 copy_notebook_link (L4987): copy [[current notebook]]."""
        if self.notebook_name_provider is None:
            return
        name = self.notebook_name_provider()
        QApplication.clipboard().setText(f"[[{name}]]")

    def delete_object_at(self, position, is_file=False):
        """Remove the object char (undoable). Ephemeral label lines under
        images/video thumbs go with it; the actual file cleanup belongs to
        core.attachments.cleanup_unused, never called here (v1
        delete_attachment leaves files for cleanup too)."""
        doc = self.document()
        if doc.characterAt(position) != OBJECT_CHAR:
            return
        cursor = QTextCursor(doc)
        cursor.setPosition(position)
        end = position + 1
        block = doc.findBlock(position)
        next_block = block.next()
        if next_block.isValid() and self._block_is_ephemeral(next_block):
            # image/video: swallow the label line too (v1 delete_attachment
            # removes the imgname_/file_ ranges with their newline).
            end = next_block.position() + max(next_block.length() - 1, 0)
        elif is_file and doc.characterAt(position + 1) == "\u2029":
            # bare file chip: take the trailing newline like v1.
            end = position + 2
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.beginEditBlock()
        cursor.removeSelectedText()
        cursor.endEditBlock()

    @staticmethod
    def _block_is_ephemeral(block):
        from noteboard.ui.editor.document import PROP_EPHEMERAL
        saw = False
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                saw = True
                if not frag.charFormat().hasProperty(PROP_EPHEMERAL):
                    return False
            it += 1
        return saw

    # ── strikethrough / highlight (marker-text edits) ────────────────────
    #
    # v1 kept these as Tk tags (apply_highlight L5055, apply_strikethrough
    # L5130, _toggle_line_highlight L5087) that serialized to [HL:]/[STRIKE]
    # markers on save. In v2 the document text IS the marker text, so the
    # commands edit the markers directly — each command one undo step.

    def _doc_text(self):
        return self.document().toPlainText()

    def _strike_open_at(self, pos):
        """True when the char at *pos* falls inside an open [STRIKE] span."""
        last = None
        for m in STRIKE_TOKEN_RE.finditer(self._doc_text(), 0, pos):
            last = m.group(0)
        return last == STRIKE_OPEN

    def _strip_tokens(self, regex, start, end):
        """Remove all *regex* tokens fully inside [start, end); returns the
        number of characters removed."""
        doc = self.document()
        spans = [(m.start(), m.end())
                 for m in regex.finditer(self._doc_text(), start, end)]
        for s, e in reversed(spans):
            c = QTextCursor(doc)
            c.setPosition(s)
            c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
            c.removeSelectedText()
        return sum(e - s for s, e in spans)

    def apply_strikethrough(self):
        """Wrap the selection in [STRIKE]..[/STRIKE] (v1 apply_strikethrough
        L5130). Same-type markers inside the range are stripped first."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        doc = self.document()
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        try:
            end -= self._strip_tokens(STRIKE_TOKEN_RE, start, end)
            c = QTextCursor(doc)
            c.setPosition(end)
            c.insertText(STRIKE_CLOSE, QTextCharFormat())
            c.setPosition(start)
            c.insertText(STRIKE_OPEN, QTextCharFormat())
        finally:
            edit.endEditBlock()

    def remove_strikethrough(self):
        """Strip [STRIKE] markers from the selection (v1 remove_strikethrough
        L5138). When the selection sits inside a larger span, the span is
        split around it — matching what v1's tag_remove serialized."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        doc = self.document()
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        try:
            open_at_start = self._strike_open_at(start)
            end -= self._strip_tokens(STRIKE_TOKEN_RE, start, end)
            open_at_end = self._strike_open_at(end)
            c = QTextCursor(doc)
            if open_at_end:
                c.setPosition(end)
                c.insertText(STRIKE_OPEN, QTextCharFormat())
            if open_at_start:
                c.setPosition(start)
                c.insertText(STRIKE_CLOSE, QTextCharFormat())
            added = ((len(STRIKE_OPEN) if open_at_end else 0)
                     + (len(STRIKE_CLOSE) if open_at_start else 0))
            self._strip_empty_strike_pairs(start, end + added)
        finally:
            edit.endEditBlock()

    def _strip_empty_strike_pairs(self, start, end):
        """Remove no-op "[STRIKE][/STRIKE]" pairs on the lines touched."""
        doc = self.document()
        lo = doc.findBlock(max(0, start)).position()
        b = doc.findBlock(min(end, doc.characterCount() - 1))
        hi = b.position() + max(b.length() - 1, 0)
        text = self._doc_text()
        pair = STRIKE_OPEN + STRIKE_CLOSE
        spans = []
        i = text.find(pair, lo)
        while i != -1 and i < hi:
            spans.append((i, i + len(pair)))
            i = text.find(pair, i + len(pair))
        for s, e in reversed(spans):
            c = QTextCursor(doc)
            c.setPosition(s)
            c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
            c.removeSelectedText()

    def _line_has_color(self, block, color):
        """Line already carries highlight *color* (its own open marker or a
        span carried in from a previous line via the highlighter state)."""
        if f"[HL:{color}]" in block.text():
            return True
        prev = block.previous()
        state = prev.userState() if prev.isValid() else -1
        if state > 0:
            idx = (state >> _HL_SHIFT) & _HL_MASK
            return idx == HIGHLIGHT_NAMES.index(color) + 1
        return False

    def _line_has_any_highlight(self, block):
        if not block.isValid():
            return False
        if HL_OPEN_RE.search(block.text()):
            return True
        prev = block.previous()
        state = prev.userState() if prev.isValid() else -1
        return state > 0 and ((state >> _HL_SHIFT) & _HL_MASK) > 0

    def apply_highlight(self, color):
        """Highlight the selection's lines with *color* (v1 apply_highlight
        L5055: line-granular, existing colors replaced)."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return
        self._highlight_lines(cursor.selectionStart(), cursor.selectionEnd(),
                              color, toggle=False)

    def remove_highlight(self):
        """Strip highlight markers from the selection's lines (or the
        cursor line) — v1 remove_highlight / _toggle_line_highlight_remove."""
        cursor = self.textCursor()
        self._highlight_lines(cursor.selectionStart(), cursor.selectionEnd(),
                              None, toggle=False)

    def toggle_line_highlight(self, color):
        """Cmd/Ctrl+1..5 (v1 _toggle_line_highlight L5087): toggle *color*
        on the cursor line or the selected lines; off only when every
        non-empty line already has it."""
        cursor = self.textCursor()
        self._highlight_lines(cursor.selectionStart(), cursor.selectionEnd(),
                              color, toggle=True)

    def _highlight_lines(self, start, end, color, toggle):
        doc = self.document()
        first = doc.findBlock(start).blockNumber()
        last = doc.findBlock(end).blockNumber()
        numbers = [n for n in range(first, last + 1)
                   if not self._block_is_ephemeral(doc.findBlockByNumber(n))]
        if not numbers:
            return
        wrap = color is not None
        if toggle and wrap:
            # off only when ALL non-empty lines already carry this color
            all_have = True
            for n in numbers:
                block = doc.findBlockByNumber(n)
                if not strip_markers(block.text()).strip():
                    continue
                if not self._line_has_color(block, color):
                    all_have = False
                    break
            wrap = not all_have
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        try:
            for n in reversed(numbers):  # last→first keeps positions valid
                block = doc.findBlockByNumber(n)
                base = block.position()
                spans = [(m.start(), m.end())
                         for m in HL_TOKEN_RE.finditer(block.text())]
                for s, e in reversed(spans):
                    c = QTextCursor(doc)
                    c.setPosition(base + s)
                    c.setPosition(base + e, QTextCursor.MoveMode.KeepAnchor)
                    c.removeSelectedText()
                if wrap:
                    block = doc.findBlockByNumber(n)
                    text = block.text()
                    if not strip_markers(text).strip():
                        continue  # v1 skips empty lines
                    c = QTextCursor(doc)
                    c.setPosition(block.position() + len(text))
                    c.insertText(HL_CLOSE, QTextCharFormat())
                    c.setPosition(block.position())
                    c.insertText(f"[HL:{color}]", QTextCharFormat())
        finally:
            edit.endEditBlock()

    # ── selection as marker text ─────────────────────────────────────────

    def selection_marker_text(self):
        """The selection serialized to marker text (v1
        _get_selected_content_with_markers L5148): objects re-emit their
        [IMAGE:]/[FILE:] markers, ephemeral lines/labels are skipped."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return ""
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        doc = self.document()
        parts = []
        block = doc.findBlock(start)
        while block.isValid() and block.position() < end:
            texts = []
            saw_fragment = False
            all_ephemeral = True
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    fs = frag.position()
                    fe = fs + frag.length()
                    if fe > start and fs < end:
                        saw_fragment = True
                        cf = frag.charFormat()
                        if not cf.hasProperty(PROP_EPHEMERAL):
                            all_ephemeral = False
                            texts.append(
                                self._clip_fragment(frag, cf, start, end))
                it += 1
            if not (saw_fragment and all_ephemeral):
                parts.append("".join(texts))
            block = block.next()
        return "\n".join(parts)

    @staticmethod
    def _clip_fragment(frag, cf, start, end):
        """Marker text for the part of *frag* inside [start, end)."""
        fs = frag.position()
        text = frag.text()
        sub = text[max(start - fs, 0):min(end - fs, len(text))]
        if cf.hasProperty(PROP_FILE_LINK):
            name = cf.property(PROP_INTERNAL_NAME)
            return f"[FILE:{name}]" * sub.count(OBJECT_CHAR)
        if cf.isImageFormat():
            name = cf.property(PROP_INTERNAL_NAME)
            if name is None:
                return ""
            width = int(cf.property(PROP_IMAGE_WIDTH) or 0)
            marker = (f"[IMAGE:{name}:{width}]" if width > 0
                      else f"[IMAGE:{name}]")
            return marker * sub.count(OBJECT_CHAR)
        return sub.replace(LINE_SEP, "\n").replace(OBJECT_CHAR, "")

    # ── keys ─────────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        # v1 handle_tab (L7862): multi-line selection indents each line;
        # otherwise insert 4 spaces at the cursor.
        if key == Qt.Key.Key_Tab and mods == Qt.KeyboardModifier.NoModifier:
            if self._selection_spans_lines():
                self.indent_selection()
            else:
                self.textCursor().insertText("    ")
            event.accept()
            return
        # v1 handle_shift_tab (L7888): Shift+Tab arrives as Backtab.
        if key == Qt.Key.Key_Backtab:
            self.unindent_selection()
            event.accept()
            return
        # Cmd/Ctrl+1..5: quick line highlight (v1 setup_undo_redo L4858)
        if (mods & Qt.KeyboardModifier.ControlModifier
                and Qt.Key.Key_1 <= key <= Qt.Key.Key_5):
            self.toggle_line_highlight(HIGHLIGHT_NAMES[key - Qt.Key.Key_1])
            event.accept()
            return
        super().keyPressEvent(event)
        if key in _NAV_FORWARD or key in _NAV_BACKWARD:
            self._jump_over_ephemeral(
                key, bool(mods & Qt.KeyboardModifier.ShiftModifier))

    def _jump_over_ephemeral(self, key, keep_anchor):
        """Keep the cursor out of ephemeral lines (URL previews, labels):
        after a movement key lands inside one, hop over it."""
        cursor = self.textCursor()
        block = cursor.block()
        if not self._block_is_ephemeral(block):
            return
        forward = key in _NAV_FORWARD
        b = block.next() if forward else block.previous()
        while b.isValid() and self._block_is_ephemeral(b):
            b = b.next() if forward else b.previous()
        if not b.isValid():  # hit the document edge: bounce back
            b = block.previous() if forward else block.next()
            while b.isValid() and self._block_is_ephemeral(b):
                b = b.previous() if forward else b.next()
            if not b.isValid():
                return
        target = (b.position() if b.blockNumber() > block.blockNumber()
                  else b.position() + max(b.length() - 1, 0))
        mode = (QTextCursor.MoveMode.KeepAnchor if keep_anchor
                else QTextCursor.MoveMode.MoveAnchor)
        cursor.setPosition(target, mode)
        self.setTextCursor(cursor)

    def _selection_spans_lines(self):
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return False
        doc = self.document()
        return (doc.findBlock(cursor.selectionStart()).blockNumber()
                != doc.findBlock(cursor.selectionEnd()).blockNumber())

    def indent_selection(self):
        """Indent the selected lines (or the cursor line) by 4 spaces —
        one undo step (v1 handle_tab / indent_text)."""
        doc = self.document()
        cursor = self.textCursor()
        first = doc.findBlock(cursor.selectionStart()).blockNumber()
        last = doc.findBlock(cursor.selectionEnd()).blockNumber()
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        try:
            for n in range(first, last + 1):
                block = doc.findBlockByNumber(n)
                edit.setPosition(block.position())
                edit.insertText("    ", QTextCharFormat())
        finally:
            edit.endEditBlock()

    def unindent_selection(self):
        """Remove up to 4 leading spaces from each selected line (or the
        cursor line) — one undo step (v1 handle_shift_tab)."""
        doc = self.document()
        cursor = self.textCursor()
        first = doc.findBlock(cursor.selectionStart()).blockNumber()
        last = doc.findBlock(cursor.selectionEnd()).blockNumber()
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        try:
            for n in range(first, last + 1):
                block = doc.findBlockByNumber(n)
                text = block.text()
                count = 0
                while count < min(4, len(text)) and text[count] == ' ':
                    count += 1
                if count:
                    edit.setPosition(block.position())
                    edit.setPosition(block.position() + count,
                                     QTextCursor.MoveMode.KeepAnchor)
                    edit.removeSelectedText()
        finally:
            edit.endEditBlock()
