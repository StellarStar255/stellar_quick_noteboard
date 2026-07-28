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
"""

import os
import re

from PySide6.QtCore import QElapsedTimer, QPoint, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import (QDesktopServices, QImage, QTextCharFormat,
                           QTextCursor)
from PySide6.QtWidgets import QApplication, QMenu, QTextEdit

from noteboard.core.attachments import generate_video_thumbnail, is_video_file
from noteboard.core.i18n import Translator
from noteboard.core.markers import (HL_CLOSE, HL_OPEN_RE, NOTEBOOK_LINK_RE,
                                    STRIKE_CLOSE, STRIKE_OPEN, TASK_RE,
                                    URL_RE, strip_markers)
from noteboard.core.theme import HIGHLIGHT_NAMES
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
        m = TASK_RE.match(text)
        if m and len(m.group(1)) <= col <= m.end(3) + 1:
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

    def _toggle_task_at(self, pos):
        """Toggle a - [ ] / - [x] checkbox when its marker span is clicked
        (v1 _on_task_box_click L5577). One undo step."""
        cursor = self.cursorForPosition(pos)
        block = cursor.block()
        col = cursor.positionInBlock()
        m = TASK_RE.match(block.text())
        if not m:
            return False
        indent = len(m.group(1))
        if not (indent <= col <= m.end(3) + 1):  # box span through ']'
            return False
        state_pos = block.position() + m.start(3)
        new_state = ' ' if m.group(3) in 'xX' else 'x'
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
            # Placeholder attachment menu — the full v1 menu set (copy
            # link/file, reveal, …) arrives with M6. Accepting the event
            # here is the Qt equivalent of v1's "break" fix: only ONE
            # menu may show for a click.
            event.accept()
            menu = QMenu(self)
            menu.addAction("Open", lambda: self._open_object(hit))
            menu.addAction("Copy Path", lambda: self._copy_path(hit))
            menu.addSeparator()
            menu.addAction("Delete", lambda: self.delete_object_at(
                hit.position, hit.is_file))
            menu.exec(event.globalPos())
            return
        self._show_text_context_menu(event)

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

    def _copy_path(self, hit):
        path = self.marker_doc.attachment_path(hit.name)
        if path:
            QApplication.clipboard().setText(path)

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
