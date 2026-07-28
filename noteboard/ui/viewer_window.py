"""Floating notebook viewer windows (M6).

Port of v1 _open_notebook_viewer (QuickNoteBoard.py L2068-2240): an
independent, non-modal, editable window per notebook, opened from the
sidebar context menu. v1 needed ~600 lines of duplicated _viewer_* code
(context-swap hacks over the single Tk text widget); v2 simply instantiates
the M2-M5 editor stack — MarkerDocument + MarkdownHighlighter +
NoteTextEdit + UrlPreviewManager — a second time, so paste/copy/cut,
markdown styling, images/files, task boxes and highlights all work as in
the main editor for free.

Sync rules (v1 exact directions, see MainWindow for the other half):
- autosave (2000ms debounce after an edit, v1 viewer._nb_save_timer)
  writes notes.txt only — it does NOT touch the main editor (v1
  on_viewer_modified only called _viewer_save);
- Cmd+S and window close save AND emit ``saved`` — the main window
  reloads from disk when it is showing the same notebook (v1
  on_viewer_save / on_viewer_close → _reload_current_from_disk);
- a full main-editor save PULLS from an open viewer of the current
  notebook (viewer wins) and saves all other viewers (v1 save_notes
  L3960-3975 → _sync_from_viewer) — implemented in MainWindow.save_notes.
"""

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow

from noteboard.core.fonts import mono_font, system_font
from noteboard.ui.editor.document import MarkerDocument
from noteboard.ui.editor.highlighter import MarkdownHighlighter
from noteboard.ui.editor.note_edit import NoteTextEdit
from noteboard.ui.editor.url_preview import UrlPreviewManager

AUTOSAVE_MS = 2000  # v1 viewer save debounce


class ViewerWindow(QMainWindow):

    #: notebook name — emitted after an EXPLICIT save (Cmd+S / close);
    #: the main window reloads when it shows the same notebook.
    saved = Signal(str)
    #: notebook name — emitted when the window closes.
    closed = Signal(str)

    def __init__(self, store, notebook, translator, theme, cfg,
                 parent=None):
        super().__init__(parent)
        self.store = store
        self.notebook = notebook
        tr = translator.tr
        self.setWindowTitle(f"{tr('nb_viewer_title')} - {notebook}")
        self.resize(600, 700)  # v1 geometry("600x700")
        if cfg.get("always_on_top"):
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        # ── the shared editor stack, wired to this notebook ──
        store.ensure_attachments_dir(notebook)
        self.marker_doc = MarkerDocument(parent=self)
        self.marker_doc.config = cfg  # share image_width / show_image_name
        self.marker_doc.theme = theme
        self.marker_doc.ui_font_family = system_font()
        self.marker_doc.attachments_dir = store.attachments_path(notebook)
        self.marker_doc.filename_map = store.load_filename_map(notebook)
        self.marker_doc.attachment_saver = self._on_attachment_saved
        font_size = int(cfg.get("font_size") or 12)
        doc = self.marker_doc.document
        doc.setDefaultFont(QFont(system_font(), font_size))
        self.highlighter = MarkdownHighlighter(
            doc, theme, base_font_size=font_size, mono_family=mono_font())
        self.editor = NoteTextEdit(self.marker_doc, self.highlighter, self)
        self.editor.translator = translator
        self.editor.notebook_name_provider = lambda: notebook
        pad = int(cfg.get("text_padding") or 0)
        self.editor.setStyleSheet(
            f"QTextEdit {{ background-color: {theme['text_bg']};"
            f" color: {theme['text_fg']};"
            f" selection-background-color: {theme['text_select_bg']};"
            f" selection-color: {theme['list_select_fg']};"
            f" border: none;"
            f" padding-left: {pad}px; padding-right: {pad}px; }}")
        self.setCentralWidget(self.editor)

        self.url_previews = UrlPreviewManager(
            self.marker_doc,
            cache=store.load_url_title_cache(),
            save_cache=store.save_url_title_cache,
            parent=self)

        self._loading = True
        try:
            self.marker_doc.load(store.load_note_text(notebook))
        finally:
            self._loading = False
        self.url_previews.rescan()

        # ── autosave (v1 on_viewer_modified, 2000ms) ──
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(AUTOSAVE_MS)
        self._save_timer.timeout.connect(self.save_now)
        doc.contentsChanged.connect(self._on_content_changed)

        # Cmd/Ctrl+S: save and sync the main editor (v1 on_viewer_save)
        save_sc = QShortcut(QKeySequence(QKeySequence.StandardKey.Save),
                            self)
        save_sc.activated.connect(self.save_and_sync)

    # ── editing / saving ─────────────────────────────────────────────

    def _on_content_changed(self):
        if (self._loading or self.url_previews.applying
                or not self.marker_doc.document.isModified()):
            return
        self._save_timer.start()
        self.url_previews.schedule()

    def _on_attachment_saved(self, internal, original=None, path=None):
        """Persist this notebook's filename map (pasted screenshots carry
        no original name and are never mapped, as v1)."""
        if not original:
            return
        self.marker_doc.filename_map[internal] = {"name": original,
                                                  "path": path}
        self.store.save_filename_map(self.notebook,
                                     self.marker_doc.filename_map)

    def save_now(self):
        """v1 _viewer_save: serialize → notes.txt. No main-editor sync
        (the autosave path never synced in v1 either)."""
        self._save_timer.stop()
        try:
            self.store.save_note_text(self.notebook,
                                      self.marker_doc.serialize())
            self.marker_doc.document.setModified(False)
        except OSError as e:
            print(f"Error saving viewer {self.notebook}: {e}")

    def save_and_sync(self):
        """Cmd+S: save, then let the main window reload if it is showing
        this notebook (v1 on_viewer_save)."""
        self.save_now()
        self.saved.emit(self.notebook)

    # ── close (v1 on_viewer_close: save, sync, destroy) ──────────────

    def closeEvent(self, event):
        self.save_now()
        self.saved.emit(self.notebook)
        self.closed.emit(self.notebook)
        event.accept()
