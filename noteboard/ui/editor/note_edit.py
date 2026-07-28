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
"""

import os

from PySide6.QtCore import QElapsedTimer, QPoint, QRectF, Qt, QUrl
from PySide6.QtGui import (QDesktopServices, QImage, QTextCharFormat,
                           QTextCursor)
from PySide6.QtWidgets import QApplication, QMenu, QTextEdit

from noteboard.core.attachments import generate_video_thumbnail, is_video_file
from noteboard.ui.editor import attachments_ui
from noteboard.ui.editor.document import (MAX_IMAGE_WIDTH, MIN_IMAGE_WIDTH,
                                          OBJECT_CHAR, PROP_FILE_LINK,
                                          PROP_INTERNAL_NAME)

EDGE_THRESHOLD = 25   # v1 get_image_resize_edge
EDGE_TOLERANCE = 10   # v1 in_x_range/in_y_range slack
MOTION_THROTTLE_MS = 50


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

    def __init__(self, marker_doc, highlighter, parent=None):
        super().__init__(parent)
        self.marker_doc = marker_doc
        self.highlighter = highlighter
        self.setDocument(marker_doc.document)
        self.setAcceptRichText(False)
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
        self.viewport().setCursor(shape)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            hit = self._hit_object(pos)
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

    # ── context menu / delete ────────────────────────────────────────────

    def contextMenuEvent(self, event):
        hit = self._hit_object(event.pos())
        if hit is not None and hit.rect.contains(event.pos().x(),
                                                 event.pos().y()):
            # Placeholder attachment menu — the full v1 menu set (copy
            # link/file, reveal, …) arrives with M5/M6.
            menu = QMenu(self)
            menu.addAction("Open", lambda: self._open_object(hit))
            menu.addAction("Copy Path", lambda: self._copy_path(hit))
            menu.addSeparator()
            menu.addAction("Delete", lambda: self.delete_object_at(
                hit.position, hit.is_file))
            menu.exec(event.globalPos())
            return
        super().contextMenuEvent(event)

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

    # ── keys ─────────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        # v1 handle_tab basic case; multi-line indent comes in M5.
        if (event.key() == Qt.Key.Key_Tab
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            self.textCursor().insertText("    ")
            event.accept()
            return
        super().keyPressEvent(event)
