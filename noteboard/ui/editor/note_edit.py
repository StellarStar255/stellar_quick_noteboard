"""The note editor widget.

Thin QTextEdit over a MarkerDocument: it never sets char formats itself
(styling belongs to the highlighter, content to the document), it only
tracks the cursor's block so markers on the active line un-collapse.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTextEdit


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

    def insertFromMimeData(self, source):
        # M2: plain-text paste only (rich/image/internal paste comes later).
        if source.hasText():
            self.insertPlainText(source.text())

    def keyPressEvent(self, event):
        # v1 handle_tab basic case; multi-line indent comes in M5.
        if (event.key() == Qt.Key.Key_Tab
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            self.textCursor().insertText("    ")
            event.accept()
            return
        super().keyPressEvent(event)
