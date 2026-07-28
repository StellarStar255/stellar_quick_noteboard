"""Application entry point.

- ``python -m noteboard``                 the real app (M4 shell) on the
  real data layout (cwd, or the per-user data dir when frozen /
  STELLAR_NOTEBOARD_DATA_DIR is set — port of v1 __main__ L9571).
- ``python -m noteboard <notes.txt>``     the M3 single-file spike window
  (kept for quick editor testing against one file).
"""

import json
import os
import sys

from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMainWindow

from noteboard.core.fonts import mono_font, system_font
from noteboard.core.paths import atomic_write_json, atomic_write_text
from noteboard.core.theme import THEMES
from noteboard.ui.editor.document import MarkerDocument
from noteboard.ui.editor.highlighter import MarkdownHighlighter
from noteboard.ui.editor.note_edit import NoteTextEdit

BASE_FONT_SIZE = 13

# Hardcoded spike config (real config plumbing lands in M4+).
SPIKE_CONFIG = {"image_width": 400, "show_image_name": True}


class SpikeWindow(QMainWindow):

    def __init__(self, path):
        super().__init__()
        self.path = os.path.abspath(path)
        t = THEMES["dark"]

        attachments = os.path.join(os.path.dirname(self.path), "attachments")
        self.marker_doc = MarkerDocument(attachments_dir=attachments,
                                         parent=self)
        self.marker_doc.config = dict(SPIKE_CONFIG)
        self.marker_doc.theme = t
        self.marker_doc.ui_font_family = system_font()
        self.marker_doc.filename_map = self._load_filename_map(attachments)
        self.marker_doc.attachment_saver = self._on_attachment_saved
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

    @staticmethod
    def _load_filename_map(attachments_dir):
        """attachments/filename_map.json, exactly as v1 stores it."""
        map_path = os.path.join(attachments_dir, "filename_map.json")
        if os.path.exists(map_path):
            try:
                with open(map_path, encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception as e:
                print(f"Error loading filename map: {e}")
        return {}

    def _on_attachment_saved(self, internal, original=None, path=None):
        """attachment_saver callback: record imported files in the
        filename map (pasted screenshots carry no original name, matching
        v1 paste_image which never maps them)."""
        if not original:
            return
        self.marker_doc.filename_map[internal] = {"name": original,
                                                  "path": path}
        attachments = self.marker_doc.attachments_dir
        os.makedirs(attachments, exist_ok=True)
        atomic_write_json(os.path.join(attachments, "filename_map.json"),
                          self.marker_doc.filename_map,
                          ensure_ascii=False, indent=2)

    def _save(self):
        atomic_write_text(self.path, self.marker_doc.serialize())
        self.marker_doc.document.setModified(False)

    def _refresh_title(self, *_):
        star = "* " if self.marker_doc.document.isModified() else ""
        self.setWindowTitle(f"{star}{self.path}")


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if len(argv) >= 2:
        # Single-file spike mode (M3), kept behind the file argument.
        app = QApplication(argv)
        window = SpikeWindow(argv[1])
        window.show()
        return app.exec()

    # Real app. Installed (frozen) builds keep user data in a per-user
    # directory; running from source uses the cwd (v1 __main__ L9571).
    from noteboard.core.paths import user_data_dir
    from noteboard.core.storage import NoteStore
    from noteboard.core.version import IS_FROZEN

    if IS_FROZEN or os.environ.get("STELLAR_NOTEBOARD_DATA_DIR"):
        data_dir = user_data_dir()
        os.makedirs(data_dir, exist_ok=True)
        os.chdir(data_dir)

    app = QApplication(argv)
    from noteboard.ui.main_window import MainWindow
    window = MainWindow(NoteStore("."))
    window.show()
    return app.exec()
