"""M2 spike shell: a bare window hosting the new editor stack.

Run with:  python -m noteboard <path/to/notes.txt>
"""

import os
import sys

from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMainWindow

from noteboard.core.fonts import mono_font, system_font
from noteboard.core.paths import atomic_write_text
from noteboard.core.theme import THEMES
from noteboard.ui.editor.document import MarkerDocument
from noteboard.ui.editor.highlighter import MarkdownHighlighter
from noteboard.ui.editor.note_edit import NoteTextEdit

BASE_FONT_SIZE = 13


class SpikeWindow(QMainWindow):

    def __init__(self, path):
        super().__init__()
        self.path = os.path.abspath(path)
        t = THEMES["dark"]

        attachments = os.path.join(os.path.dirname(self.path), "attachments")
        self.marker_doc = MarkerDocument(attachments_dir=attachments,
                                         parent=self)
        doc = self.marker_doc.document
        doc.setDefaultFont(QFont(system_font(), BASE_FONT_SIZE))
        self.highlighter = MarkdownHighlighter(
            doc, t, base_font_size=BASE_FONT_SIZE, mono_family=mono_font())
        self.editor = NoteTextEdit(self.marker_doc, self.highlighter)
        self.editor.setStyleSheet(
            f"QTextEdit {{ background-color: {t['text_bg']};"
            f" color: {t['text_fg']};"
            f" selection-background-color: {t['text_select_bg']};"
            f" selection-color: {t['list_select_fg']};"
            f" border: none; padding: 8px; }}")
        self.setCentralWidget(self.editor)

        text = ""
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as fh:
                text = fh.read()
        self.marker_doc.load(text)

        doc.modificationChanged.connect(self._refresh_title)
        save = QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self)
        save.activated.connect(self._save)
        self.resize(900, 700)
        self._refresh_title()

    def _save(self):
        atomic_write_text(self.path, self.marker_doc.serialize())
        self.marker_doc.document.setModified(False)

    def _refresh_title(self, *_):
        star = "* " if self.marker_doc.document.isModified() else ""
        self.setWindowTitle(f"{star}{self.path}")


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if len(argv) < 2:
        print("usage: python -m noteboard <path/to/notes.txt>",
              file=sys.stderr)
        return 2
    app = QApplication(argv)
    window = SpikeWindow(argv[1])
    window.show()
    return app.exec()
