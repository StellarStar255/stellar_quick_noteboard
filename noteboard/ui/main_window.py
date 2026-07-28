"""The Quick Note Board application shell (M4).

Port of the v1 NoteApp window chrome (QuickNoteBoard.py __init__ L509-938):
toolbar, sidebar + splitter, recycle box, status bar, notebook lifecycle,
config load/save, autosave, i18n and theming — on top of the M1-M3 core
(NoteStore) and editor stack (MarkerDocument/NoteTextEdit/Highlighter).
"""

import os
import platform
import re
import shutil
from datetime import datetime

from PySide6.QtCore import QThreadPool, QTimer, Qt
from PySide6.QtGui import (QCursor, QFont, QGuiApplication, QIcon,
                           QKeySequence, QShortcut, QTextCharFormat,
                           QTextCursor)
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog,
                               QLabel, QMainWindow, QMenu, QPlainTextEdit,
                               QSplitter, QToolBar, QToolButton, QVBoxLayout,
                               QWidget)

from noteboard.core import export as export_core
from noteboard.core.attachments import cleanup_unused, referenced_attachments
from noteboard.core.fonts import mono_font, system_font
from noteboard.core.markers import strip_markers
from noteboard.core.paths import atomic_write_text, resource_path
from noteboard.core.storage import CONFIG_KEYS
from noteboard.core.theme import THEMES
from noteboard.core.version import APP_VERSION, IS_FROZEN
from noteboard.core.i18n import Translator
from noteboard.ui import dialogs
from noteboard.ui.backup_dialog import BackupRestoreDialog
from noteboard.ui.editor.document import MarkerDocument
from noteboard.ui.editor.highlighter import MarkdownHighlighter
from noteboard.ui.editor.note_edit import NoteTextEdit
from noteboard.ui.editor.url_preview import UrlPreviewManager
from noteboard.ui.find_bar import FindBar
from noteboard.ui.global_search import GlobalSearchDialog
from noteboard.ui.outline_panel import OutlinePanel
from noteboard.ui.qss import build_qss
from noteboard.ui.recycle_box import RecycleBox
from noteboard.ui.sidebar import Sidebar
from noteboard.ui.update_dialog import UpdateFlow
from noteboard.ui.viewer_window import ViewerWindow

_IS_LINUX = platform.system() == "Linux"

# v1 option lists (__init__ L577-590)
ICON_SIZES = [16, 20, 24, 32, 40, 48]
UI_FONT_SIZES = [11, 12, 13, 14, 15, 16, 18, 20]
PADDING_SIZES = [0, 5, 10, 15, 20, 30, 40]

AUTOSAVE_MS = 2000        # debounce on document contentsChanged
WORDCOUNT_MS = 400        # v1 _schedule_word_count
CONFIG_SAVE_MS = 1000     # v1 _deferred_save_config

# Tk geometry string "WxH+X+Y" (offsets may be negative: "+-5")
_GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)$")

# v1 _update_word_count (L5994): CJK chars count as one word each
_WC_RE = re.compile(r"[一-鿿㐀-䶿぀-ヿ가-힯]|[A-Za-z0-9_'’-]+")


class MainWindow(QMainWindow):

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        store.ensure_notebooks_dir()
        store.migrate_legacy_history()

        # ── config: all CONFIG_KEYS with defaults, then disk overrides ──
        self.cfg = dict(CONFIG_KEYS)
        self.cfg.update(store.load_config())
        if self.cfg.get("theme") not in THEMES:
            self.cfg["theme"] = "dark"
        if self.cfg.get("language") not in ("zh", "en"):
            self.cfg["language"] = "zh"
        self.theme_name = self.cfg["theme"]
        self.translator = Translator(self.cfg["language"])
        self.ui_font_size = (self.cfg.get("ui_font_size")
                             or self._auto_ui_font_size())
        self._sidebar_width = int(self.cfg.get("sidebar_width") or 150)
        self.sidebar_visible = bool(self.cfg.get("sidebar_visible", True))

        # startup notebook: saved value if it still exists, else first
        notebooks = store.ordered_notebooks()
        nb = self.cfg.get("current_notebook") or store.DEFAULT_NOTEBOOK
        self.current_notebook = nb if nb in notebooks else notebooks[0]

        self._dirty = False
        self._loading = False
        self._pool = QThreadPool.globalInstance()
        self.viewers = {}  # notebook name -> ViewerWindow (v1 _notebook_viewers)

        # ── timers ──
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(AUTOSAVE_MS)
        self._autosave_timer.timeout.connect(self.save_notes)
        self._wc_timer = QTimer(self)
        self._wc_timer.setSingleShot(True)
        self._wc_timer.setInterval(WORDCOUNT_MS)
        self._wc_timer.timeout.connect(self._update_word_count)
        self._config_timer = QTimer(self)
        self._config_timer.setSingleShot(True)
        self._config_timer.setInterval(CONFIG_SAVE_MS)
        self._config_timer.timeout.connect(self._save_config)

        self._build_ui()
        self._set_window_icon()
        self._apply_theme(self.theme_name)
        self._apply_config()
        self._load_notebook(self.current_notebook)
        self._update_word_count()
        # restore the outline panel's open state (v1 _outline_restore)
        if self.cfg.get("outline_visible"):
            self.outline.toggle()
        # silent update check on installed builds only (v1 __main__
        # root.after(5000, ...) when frozen): errors and "up to date"
        # are swallowed, only a newer release prompts.
        self._update_flow = None
        if IS_FROZEN:
            QTimer.singleShot(5000,
                              lambda: self.check_for_updates(silent=True))

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self):
        # Toolbar — left: checkboxes + ☰; right (visual order per v1's
        # right-to-left packing): 搜索 目录 保存 历史 笔记本 图标 UI字号
        # 左边距 | → A- A+ | EN/中 theme.
        self.toolbar = QToolBar(self)
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        # The toolbar is the app's only control surface — it must never be
        # hidable (macOS offers "Hide Toolbar" on right-click by default,
        # which would strand the user with no way back).
        self.toolbar.toggleViewAction().setVisible(False)
        self.toolbar.toggleViewAction().setEnabled(False)
        self.addToolBar(self.toolbar)

        # Native menu bar: gives 检查更新 a discoverable home (macOS global
        # menu) independent of the toolbar menus.
        self._menu_help = self.menuBar().addMenu("")
        self.act_check_update = self._menu_help.addAction("")
        self.act_check_update.triggered.connect(
            lambda: self.check_for_updates(False))

        self.chk_pin = QCheckBox(self)
        self.chk_pin.toggled.connect(self._toggle_topmost)
        self.toolbar.addWidget(self.chk_pin)
        self.chk_img_name = QCheckBox(self)
        self.chk_img_name.toggled.connect(self._toggle_show_image_name)
        self.toolbar.addWidget(self.chk_img_name)
        self.chk_recycle = QCheckBox(self)
        self.chk_recycle.toggled.connect(self._toggle_recycle_box)
        self.toolbar.addWidget(self.chk_recycle)
        self.toolbar.addSeparator()
        self.btn_sidebar = self._tool_btn("☰", self.toggle_sidebar)

        spacer = QWidget(self)
        spacer.setSizePolicy(spacer.sizePolicy().Policy.Expanding,
                             spacer.sizePolicy().Policy.Preferred)
        spacer.setStyleSheet("background: transparent;")
        self.toolbar.addWidget(spacer)

        self.btn_search = self._tool_btn("", self.toggle_find_bar)
        self.btn_outline = self._tool_btn("", self.toggle_outline)
        self.btn_save = self._tool_btn("", self.save_notes)
        self.btn_history = self._tool_btn("", self.show_history)
        self.btn_notebook = self._tool_btn("", self.show_notebook_menu)
        self.btn_icon = self._tool_btn("", self.show_icon_menu)
        self.btn_ui_size = self._tool_btn("", self.show_ui_font_menu)
        self.btn_padding = self._tool_btn("", self.show_padding_menu)
        self.toolbar.addSeparator()
        self.btn_indent = self._tool_btn("→", self.indent_text)
        self.btn_font_minus = self._tool_btn("A-", self.decrease_font)
        self.btn_font_plus = self._tool_btn("A+", self.increase_font)
        self.toolbar.addSeparator()
        self.btn_lang = self._tool_btn("", self.switch_language)
        self.btn_theme = self._tool_btn("", self.toggle_theme)

        # ── splitter: sidebar | right content ──
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.setCentralWidget(self.splitter)

        self.sidebar = Sidebar(self.translator, self.splitter)
        self.sidebar.setMinimumWidth(120)  # v1 paned minsize 120
        self.sidebar.notebook_activated.connect(self.switch_notebook)
        self.sidebar.context_requested.connect(
            self.show_notebook_context_menu)
        self.sidebar.empty_context_requested.connect(
            self._show_sidebar_empty_menu)
        self.sidebar.order_dragged.connect(self._on_order_dragged)
        self.sidebar.new_requested.connect(self.create_notebook)
        self.sidebar.manage_requested.connect(self.show_order_dialog)
        self.splitter.addWidget(self.sidebar)

        right = QWidget(self.splitter)
        right.setMinimumWidth(300)  # v1 paned minsize 300
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(5)

        self.recycle = RecycleBox(self.translator, right)
        self.recycle.recycle_requested.connect(self._on_recycle)
        right_layout.addWidget(self.recycle)

        # ── editor stack (M3), wired to the store ──
        self.marker_doc = MarkerDocument(parent=self)
        self.marker_doc.config = self.cfg  # image_width / show_image_name
        self.marker_doc.ui_font_family = system_font()
        self.marker_doc.attachment_saver = self._on_attachment_saved
        doc = self.marker_doc.document
        doc.setDefaultFont(QFont(system_font(),
                                 int(self.cfg.get("font_size") or 12)))
        self.highlighter = MarkdownHighlighter(
            doc, THEMES[self.theme_name],
            base_font_size=int(self.cfg.get("font_size") or 12),
            mono_family=mono_font())
        self.editor = NoteTextEdit(self.marker_doc, self.highlighter, right)
        self.editor.translator = self.translator
        self.editor.notebook_name_provider = lambda: self.current_notebook
        self.editor.save_selection_as_notebook.connect(
            self.save_selection_as_notebook)
        self.editor.notebook_link_clicked.connect(self.open_notebook_link)

        # In-note find/replace bar, hidden above the editor (M5)
        self.find_bar = FindBar(self.editor, self.translator, right)
        right_layout.addWidget(self.find_bar)
        right_layout.addWidget(self.editor, 1)
        doc.contentsChanged.connect(self._on_content_changed)
        self.editor.selectionChanged.connect(self._wc_timer.start)

        # Floating outline / TOC panel over the editor (M6)
        self.outline = OutlinePanel(self.editor, self.translator,
                                    THEMES[self.theme_name], self.cfg,
                                    self._schedule_config_save)

        # URL title previews (ephemeral lines, never serialized)
        self.url_previews = UrlPreviewManager(
            self.marker_doc,
            cache=self.store.load_url_title_cache(),
            save_cache=self.store.save_url_title_cache,
            parent=self)

        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.splitterMoved.connect(
            lambda *_: self._schedule_config_save())

        # ── status bar: notebook name left, word count right ──
        self.status_nb_label = QLabel(self)
        self.statusBar().addWidget(self.status_nb_label)
        self.wordcount_label = QLabel(self)
        self.statusBar().addPermanentWidget(self.wordcount_label)

        # ── shortcuts ──
        save = QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self)
        save.activated.connect(self.save_notes)
        quit_sc = QShortcut(QKeySequence("Ctrl+Q"), self)
        quit_sc.activated.connect(self._confirm_quit)
        find_sc = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        find_sc.activated.connect(self.toggle_find_bar)
        # Global search: Cmd+G / Ctrl+Shift+F (v1 setup_paste_binding L4816)
        for seq in ("Ctrl+G", "Ctrl+Shift+F"):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(self.show_global_search)

        self.resize(400, 300)  # v1 default geometry, config may override
        self.retranslate()

    def _tool_btn(self, text, slot):
        btn = QToolButton(self)
        btn.setText(text)
        if slot is not None:
            btn.clicked.connect(slot)
        self.toolbar.addWidget(btn)
        return btn

    def _set_window_icon(self):
        """v1 set_window_icon (L4500): assets/quick_note_board.png via
        resource_path, so it works both frozen and from source."""
        icon_path = resource_path("assets", "quick_note_board.png")
        if not os.path.exists(icon_path):
            return
        icon = QIcon(icon_path)
        if icon.isNull():
            return
        self.setWindowIcon(icon)
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)
        self._build_tray(icon)

    def createPopupMenu(self):
        # QMainWindow's default toolbar context menu could hide the toolbar
        # with no way to restore it — suppress it entirely.
        return None

    # ── system tray ──────────────────────────────────────────────────

    def _build_tray(self, icon):
        from PySide6.QtWidgets import QSystemTrayIcon
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu(self)
        self.act_tray_show = menu.addAction("")
        self.act_tray_show.triggered.connect(self._tray_show_window)
        self.act_tray_update = menu.addAction("")
        self.act_tray_update.triggered.connect(
            lambda: self.check_for_updates(False))
        menu.addSeparator()
        self.act_tray_quit = menu.addAction("")
        self.act_tray_quit.triggered.connect(self.close)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        # The tray is built after _build_ui's retranslate pass — label it now.
        self.retranslate()

    def _tray_show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        from PySide6.QtWidgets import QSystemTrayIcon
        # Plain click toggles the window (macOS delivers only the context
        # menu, so this mainly serves Windows/Linux).
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self._tray_show_window()

    # ── software update (M7) ─────────────────────────────────────────

    def check_for_updates(self, silent=False):
        """v1 check_for_updates (L4369): the 检查更新 menu item and the
        silent startup check, via ui.update_dialog.UpdateFlow."""
        flow = UpdateFlow(self, self.translator)
        self._update_flow = flow  # keep alive across the worker hops
        flow.check(silent=silent)
        return flow

    # ── config apply / persist ───────────────────────────────────────

    def _apply_config(self):
        cfg = self.cfg
        geometry = cfg.get("geometry")
        if geometry:
            m = _GEOMETRY_RE.match(str(geometry))
            if m:
                w, h = int(m.group(1)), int(m.group(2))
                x = int(m.group(3).lstrip("+"))
                y = int(m.group(4).lstrip("+"))
                self.setGeometry(x, y, w, h)

        # block toggle handlers while restoring saved states
        for chk, key in ((self.chk_pin, "always_on_top"),
                         (self.chk_img_name, "show_image_name"),
                         (self.chk_recycle, "show_recycle_box")):
            chk.blockSignals(True)
            chk.setChecked(bool(cfg.get(key, CONFIG_KEYS[key])))
            chk.blockSignals(False)
        if self.chk_pin.isChecked():
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.recycle.setVisible(self.chk_recycle.isChecked())

        self.splitter.setSizes(
            [self._sidebar_width,
             max(300, self.width() - self._sidebar_width)])
        if not self.sidebar_visible:
            self.sidebar.setVisible(False)
            self.btn_sidebar.setText("▶")

    def _collect_config(self):
        if self.sidebar_visible:
            w = self.splitter.sizes()[0]
            if w > 1:
                self._sidebar_width = w
        g = self.geometry()
        self.cfg.update({
            "always_on_top": self.chk_pin.isChecked(),
            "font_size": int(self.cfg.get("font_size") or 12),
            "ui_font_size": self.ui_font_size,
            "show_image_name": self.chk_img_name.isChecked(),
            "geometry": f"{g.width()}x{g.height()}+{g.x()}+{g.y()}",
            "current_notebook": self.current_notebook,
            "sidebar_visible": self.sidebar_visible,
            "sidebar_width": self._sidebar_width,
            "show_recycle_box": self.chk_recycle.isChecked(),
            "theme": self.theme_name,
            "language": self.translator.language,
        })
        return self.cfg

    def _save_config(self):
        self._config_timer.stop()
        try:
            self.store.save_config(self._collect_config())
        except OSError as e:
            print(f"Error saving config: {e}")

    def _schedule_config_save(self):
        self._config_timer.start()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_config_save()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_config_save()

    @staticmethod
    def _auto_ui_font_size():
        """v1 _auto_ui_font_size: pick a size from the screen diagonal."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 13
        g = screen.geometry()
        diag = (g.width() ** 2 + g.height() ** 2) ** 0.5
        if diag >= 4000:
            target = 16
        elif diag >= 2900:
            target = 15
        elif diag >= 2200:
            target = 14
        elif diag >= 1700:
            target = 13
        else:
            target = 12
        return min(UI_FONT_SIZES, key=lambda s: abs(s - target))

    # ── theme / style ────────────────────────────────────────────────

    def _apply_theme(self, name):
        self.theme_name = name
        t = THEMES[name]
        self.setStyleSheet(build_qss(t, self.ui_font_size, system_font()))
        self.btn_theme.setText(t["theme_icon"])
        self.marker_doc.theme = t
        self.highlighter.set_theme(t)
        self.outline.apply_theme(t)
        self._apply_editor_style()

    def _apply_editor_style(self):
        t = THEMES[self.theme_name]
        pad = int(self.cfg.get("text_padding") or 0)
        self.editor.setStyleSheet(
            f"QTextEdit {{ background-color: {t['text_bg']};"
            f" color: {t['text_fg']};"
            f" selection-background-color: {t['text_select_bg']};"
            f" selection-color: {t['list_select_fg']};"
            f" border: none;"
            f" padding-left: {pad}px; padding-right: {pad}px; }}")

    def toggle_theme(self):
        self._apply_theme("light" if self.theme_name == "dark" else "dark")
        self.cfg["theme"] = self.theme_name
        self._rerender_document()  # theme-baked chips / label colors
        self._schedule_config_save()

    def _rerender_document(self):
        """Reload the document from its own serialization (v1
        reload_display): refreshes theme-dependent chips and labels.
        Pending unsaved changes stay pending."""
        was_dirty = self._dirty
        pos = self.editor.textCursor().position()
        text = self.marker_doc.serialize()
        md = self.marker_doc
        md._loaded_images.clear()
        md._natural_sizes.clear()
        self._loading = True
        try:
            md.load(text)
        finally:
            self._loading = False
        self._dirty = was_dirty
        cursor = self.editor.textCursor()
        cursor.setPosition(min(pos, max(0, md.document.characterCount() - 1)))
        self.editor.setTextCursor(cursor)
        self.url_previews.rescan()  # reload dropped the ephemeral previews

    # ── i18n ─────────────────────────────────────────────────────────

    def switch_language(self):
        self.translator.toggle()
        self.cfg["language"] = self.translator.language
        self.retranslate()
        self._schedule_config_save()

    def retranslate(self):
        """v1 _refresh_all_text: relabel every user-visible string."""
        tr = self.translator.tr
        self._menu_help.setTitle(tr("help_menu"))
        self.act_check_update.setText(tr("check_update").format(APP_VERSION))
        if getattr(self, "tray", None) is not None:
            self.act_tray_show.setText(tr("tray_show"))
            self.act_tray_update.setText(tr("check_update").format(APP_VERSION))
            self.act_tray_quit.setText(tr("tray_quit"))
            self.tray.setToolTip("Quick Note Board")
        self.chk_pin.setText(tr("pin_top"))
        self.chk_img_name.setText(tr("paste_img_name"))
        self.chk_recycle.setText(tr("recycle_box_cb"))
        self.btn_search.setText(tr("search_btn"))
        self.btn_outline.setText(tr("outline_btn"))
        self.btn_save.setText(tr("save_btn"))
        self.btn_history.setText(tr("history_btn"))
        self.btn_notebook.setText(tr("notebook_btn"))
        self.btn_icon.setText(tr("icon_btn"))
        self.btn_ui_size.setText(f"{self.ui_font_size}px")
        self.btn_padding.setText(tr("padding_btn"))
        self.btn_lang.setText(tr("lang_toggle"))
        self.sidebar.retranslate()
        self.recycle.retranslate()
        self.find_bar.retranslate()
        self.outline.retranslate()
        self._update_status_notebook()
        self._update_word_count()

    # ── notebook lifecycle ───────────────────────────────────────────

    def _refresh_sidebar(self):
        _order, shortcuts = self.store.load_order()
        self.sidebar.refresh(self.store.ordered_notebooks(), shortcuts,
                             self.current_notebook)

    def _load_notebook(self, nb):
        """Load *nb* into the editor and refresh all chrome."""
        store = self.store
        store.ensure_attachments_dir(nb)
        md = self.marker_doc
        md.attachments_dir = store.attachments_path(nb)
        md.filename_map = store.load_filename_map(nb)
        md._loaded_images.clear()
        md._natural_sizes.clear()
        self._loading = True
        try:
            md.load(store.load_note_text(nb))
        finally:
            self._loading = False
        self._dirty = False
        self.setWindowTitle(f"Quick Note Board - {nb}")
        self._update_status_notebook()
        self._refresh_sidebar()
        self._wc_timer.start()
        self.url_previews.rescan()  # cached titles now, fetch the rest
        self.find_bar.refresh()
        self.outline.update_outline()
        self.editor.setFocus()

    def switch_notebook(self, name):
        """Port of v1 switch_notebook: save current first, then load."""
        if name == self.current_notebook:
            return
        if not os.path.isdir(self.store.notebook_path(name)):
            return
        self.save_notes(quick=True)
        self._autosave_timer.stop()
        # v1 L2591: save the target's open viewer first so we load latest
        viewer = self.viewers.get(name)
        if viewer is not None:
            viewer.save_now()
        self.current_notebook = name
        self._load_notebook(name)
        self._schedule_config_save()

    # create / rename / delete (pure flows; UI wrappers below) --------

    def _do_create_notebook(self, name):
        """Create + switch. Returns an i18n error key or None."""
        if not name:
            return "nb_exists"
        if name in self.store.list_notebooks():
            return "nb_exists"
        self.store.create_notebook(name)
        self._refresh_sidebar()
        self.switch_notebook(name)
        return None

    def _do_rename_current(self, new_name):
        """Rename the current notebook. Returns an i18n error key or None."""
        if self.current_notebook == self.store.DEFAULT_NOTEBOOK:
            return "no_rename_def"
        if not new_name or new_name == self.current_notebook:
            return None
        if new_name in self.store.list_notebooks():
            return "nb_exists"
        self.store.rename_notebook(self.current_notebook, new_name)
        self.current_notebook = new_name
        self.marker_doc.attachments_dir = \
            self.store.attachments_path(new_name)
        self.setWindowTitle(f"Quick Note Board - {new_name}")
        self._update_status_notebook()
        self._refresh_sidebar()
        self._schedule_config_save()
        return None

    def _do_delete_notebook(self, name):
        """Delete *name*, falling back to the first remaining notebook
        when it was current. Returns an i18n error key or None."""
        fallback = next((n for n in self.store.ordered_notebooks()
                         if n != name), None)
        if fallback is None:
            return "no_delete_last"
        was_current = name == self.current_notebook
        if was_current:
            # discard the deleted notebook's editor state without saving
            self._autosave_timer.stop()
            self._dirty = False
        self.store.delete_notebook(name)
        if was_current:
            self.current_notebook = fallback
            self._load_notebook(fallback)
        else:
            self._refresh_sidebar()
        self._schedule_config_save()
        return None

    # UI wrappers -----------------------------------------------------

    def create_notebook(self):
        tr = self.translator.tr

        def validator(value):
            if value in self.store.list_notebooks():
                return tr("nb_exists")
            return None

        name = dialogs.ask_input(self, tr, tr("new_nb_title"),
                                 tr("nb_name_label"),
                                 confirm_text=tr("create"),
                                 validator=validator)
        if name:
            self._do_create_notebook(name)

    def rename_notebook(self):
        tr = self.translator.tr
        if self.current_notebook == self.store.DEFAULT_NOTEBOOK:
            dialogs.show_alert(self, tr, tr("warning"), tr("no_rename_def"))
            return

        def validator(value):
            if (value != self.current_notebook
                    and value in self.store.list_notebooks()):
                return tr("nb_exists")
            return None

        name = dialogs.ask_input(self, tr, tr("rename_nb_title"),
                                 tr("new_name_label"),
                                 initial=self.current_notebook,
                                 confirm_text=tr("rename"),
                                 validator=validator)
        if name:
            self._do_rename_current(name)

    def delete_notebook(self, name=None):
        tr = self.translator.tr
        name = name or self.current_notebook
        fallback = next((n for n in self.store.ordered_notebooks()
                         if n != name), None)
        if fallback is None:
            dialogs.show_alert(self, tr, tr("warning"), tr("no_delete_last"))
            return
        if dialogs.ask_confirm(self, tr, tr("confirm_del"),
                               tr("confirm_del_msg").format(name)):
            self._do_delete_notebook(name)

    def rename_specific_notebook(self, name):
        """v1 rename_specific_notebook: switch to it first, then rename."""
        tr = self.translator.tr
        if name == self.store.DEFAULT_NOTEBOOK:
            dialogs.show_alert(self, tr, tr("warning"), tr("no_rename_def"))
            return
        if name != self.current_notebook:
            self.switch_notebook(name)
        self.rename_notebook()

    # pins & ordering -------------------------------------------------

    def _apply_explicit_order(self, order):
        """Persist a user-arranged order.

        The sidebar sorts pinned notebooks by their position in the
        shortcuts list — the saved "order" list cannot override that (v1
        rule). So an explicit rearrangement must also re-sequence the
        shortcuts to match, otherwise dragging pinned items snaps back
        (a bug inherited from v1, fixed here).
        """
        _old, shortcuts = self.store.load_order()
        pinned = set(shortcuts)
        shortcuts = [n for n in order if n in pinned]
        self.store.save_order(order, shortcuts)
        self._refresh_sidebar()

    def _on_order_dragged(self, order):
        self._apply_explicit_order(order)

    def pin_notebook(self, name, pinned):
        order, shortcuts = self.store.load_order()
        if pinned and name not in shortcuts:
            shortcuts.append(name)
        elif not pinned and name in shortcuts:
            shortcuts.remove(name)
        self.store.save_order(order, shortcuts)
        self._refresh_sidebar()

    def move_notebook(self, name, delta):
        """v1 move_notebook_up/down: swap within the full ordered list."""
        order = self.store.ordered_notebooks()
        if name not in order:
            return
        idx = order.index(name)
        target = idx + delta
        if not (0 <= target < len(order)):
            return
        order[idx], order[target] = order[target], order[idx]
        self._apply_explicit_order(order)

    def show_order_dialog(self):
        tr = self.translator.tr
        dlg = dialogs.OrderDialog(self, tr, self.store.ordered_notebooks())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply_explicit_order(dlg.order())

    # export / import -------------------------------------------------

    def export_notebook(self, name=None):
        tr = self.translator.tr
        name = name or self.current_notebook
        if name == self.current_notebook:
            self.save_notes(quick=True)
        out, _f = QFileDialog.getSaveFileName(
            self, tr("export_nb"), f"{name}.zip", "ZIP (*.zip)")
        if not out:
            return
        export_core.export_zip(self.store.notebook_path(name), out)
        dialogs.show_alert(self, tr, tr("export_nb"),
                           tr("export_ok").format(out))

    def export_notebook_markdown(self):
        tr = self.translator.tr
        nb = self.current_notebook
        self.save_notes(quick=True)
        out, _f = QFileDialog.getSaveFileName(
            self, tr("export_md"), f"{nb}.md", "Markdown (*.md)")
        if not out:
            return
        mapping = self.marker_doc.filename_map
        export_core.export_markdown(
            self.store.load_note_text(nb), out,
            self.store.attachments_path(nb),
            lambda fn: self.store.display_name(mapping, fn))
        dialogs.show_alert(self, tr, tr("export_md"),
                           tr("export_ok").format(out))

    def export_notebook_html(self):
        tr = self.translator.tr
        nb = self.current_notebook
        self.save_notes(quick=True)
        out, _f = QFileDialog.getSaveFileName(
            self, tr("export_html"), f"{nb}.html", "HTML (*.html)")
        if not out:
            return
        mapping = self.marker_doc.filename_map
        html = export_core.content_to_html(
            self.store.load_note_text(nb), nb,
            self.store.attachments_path(nb),
            lambda fn: self.store.display_name(mapping, fn))
        atomic_write_text(out, html)
        dialogs.show_alert(self, tr, tr("export_html"),
                           tr("export_ok").format(out))

    def import_notebook(self):
        tr = self.translator.tr
        path, _f = QFileDialog.getOpenFileName(
            self, tr("import_nb"), "", "ZIP (*.zip)")
        if not path:
            return
        try:
            name = export_core.import_zip(
                path, self.store._p(self.store.NOTEBOOKS_DIR))
        except Exception as e:
            dialogs.show_alert(self, tr, tr("warning"),
                               tr("import_err").format(e))
            return
        self._refresh_sidebar()
        self.switch_notebook(name)

    # ── menus ────────────────────────────────────────────────────────

    def show_notebook_menu(self):
        """v1 show_notebook_menu (L2553): notebooks + lifecycle actions.
        Items whose feature lands in a later milestone are grayed out,
        never hidden (stable menu structure)."""
        tr = self.translator.tr
        menu = QMenu(self)
        for name in self.store.ordered_notebooks():
            prefix = "✓ " if name == self.current_notebook else "   "
            menu.addAction(f"{prefix}{name}",
                           lambda n=name: self.switch_notebook(n))
        menu.addSeparator()
        menu.addAction(tr("new_nb_dots"), self.create_notebook)
        menu.addAction(tr("rename_cur_nb"), self.rename_notebook)
        can_delete = len(self.store.list_notebooks()) > 1
        act = menu.addAction(tr("delete_cur_nb"),
                             lambda: self.delete_notebook())
        act.setEnabled(can_delete)
        menu.addSeparator()
        menu.addAction(tr("sort_manage"), self.show_order_dialog)
        menu.addAction(tr("global_search"), self.show_global_search)
        menu.addSeparator()
        menu.addAction(tr("export_nb"), lambda: self.export_notebook())
        menu.addAction(tr("export_md"), self.export_notebook_markdown)
        menu.addAction(tr("export_html"), self.export_notebook_html)
        menu.addAction(tr("import_nb"), self.import_notebook)
        menu.addSeparator()
        menu.addAction(tr("restore_backup"), self.show_restore_backup_dialog)
        menu.exec(QCursor.pos())

    def show_notebook_context_menu(self, name, global_pos):
        """v1 show_notebook_context_menu (L2459)."""
        tr = self.translator.tr
        _order, shortcuts = self.store.load_order()
        menu = QMenu(self)
        if name in shortcuts:
            menu.addAction(tr("unpin"),
                           lambda: self.pin_notebook(name, False))
        else:
            menu.addAction(tr("pin"), lambda: self.pin_notebook(name, True))
        menu.addSeparator()
        menu.addAction(tr("move_up"), lambda: self.move_notebook(name, -1))
        menu.addAction(tr("move_down"), lambda: self.move_notebook(name, +1))
        menu.addSeparator()
        menu.addAction(tr("open_viewer"),
                       lambda: self.open_notebook_viewer(name))
        menu.addSeparator()
        menu.addAction(tr("export_nb"), lambda: self.export_notebook(name))
        menu.addAction(tr("import_nb"), self.import_notebook)
        menu.addSeparator()
        menu.addAction(tr("rename_dots"),
                       lambda: self.rename_specific_notebook(name))
        can_delete = any(n != name for n in self.store.list_notebooks())
        act = menu.addAction(tr("delete"),
                             lambda: self.delete_notebook(name))
        act.setEnabled(can_delete)
        menu.exec(global_pos)

    def _show_sidebar_empty_menu(self, global_pos):
        tr = self.translator.tr
        menu = QMenu(self)
        menu.addAction(tr("new_nb_title"), self.create_notebook)
        menu.addAction(tr("import_nb"), self.import_notebook)
        menu.exec(global_pos)

    def show_icon_menu(self):
        """v1 show_icon_menu (L1475)."""
        tr = self.translator.tr
        menu = QMenu(self)
        current = int(self.cfg.get("icon_size") or 24)
        for size in ICON_SIZES:
            prefix = "✓ " if size == current else "   "
            menu.addAction(f"{prefix}{size}px",
                           lambda s=size: self.set_icon_size(s))
        menu.addSeparator()
        menu.addAction(tr("refresh_display"), self._rerender_document)
        menu.addAction(tr("clean_attach"), self.cleanup_orphaned_attachments)
        menu.addSeparator()
        menu.addAction(tr("check_update").format(APP_VERSION),
                       self.check_for_updates)
        menu.exec(QCursor.pos())

    def set_icon_size(self, size):
        self.cfg["icon_size"] = size
        self._schedule_config_save()
        self._rerender_document()

    def show_padding_menu(self):
        """v1 show_padding_menu (L1504)."""
        menu = QMenu(self)
        current = int(self.cfg.get("text_padding") or 10)
        for size in PADDING_SIZES:
            prefix = "✓ " if size == current else "   "
            menu.addAction(f"{prefix}{size}px",
                           lambda s=size: self.set_padding(s))
        menu.exec(QCursor.pos())

    def set_padding(self, size):
        self.cfg["text_padding"] = size
        self._apply_editor_style()
        self._schedule_config_save()

    def show_ui_font_menu(self):
        """v1 show_ui_font_menu (L1525) incl. the auto-fit option."""
        tr = self.translator.tr
        menu = QMenu(self)
        auto = self._auto_ui_font_size()
        menu.addAction(f"   {tr('ui_font_auto')} · {auto}px",
                       lambda s=auto: self.set_ui_font_size(s))
        menu.addSeparator()
        for size in UI_FONT_SIZES:
            prefix = "✓ " if size == self.ui_font_size else "   "
            menu.addAction(f"{prefix}{size}px",
                           lambda s=size: self.set_ui_font_size(s))
        menu.exec(QCursor.pos())

    def set_ui_font_size(self, size):
        self.ui_font_size = size
        self.cfg["ui_font_size"] = size
        self.setStyleSheet(build_qss(THEMES[self.theme_name], size,
                                     system_font()))
        self.btn_ui_size.setText(f"{size}px")
        self._schedule_config_save()

    # ── note font size (A+ / A-) ─────────────────────────────────────

    def _set_note_font_size(self, size):
        self.cfg["font_size"] = size
        self.marker_doc.document.setDefaultFont(QFont(system_font(), size))
        self.highlighter.base_font_size = size
        self.highlighter.set_theme(THEMES[self.theme_name])  # rebuild fmts
        self._schedule_config_save()

    def increase_font(self):
        self._set_note_font_size(int(self.cfg.get("font_size") or 12) + 2)

    def decrease_font(self):
        size = int(self.cfg.get("font_size") or 12)
        if size > 8:
            self._set_note_font_size(size - 2)

    def indent_text(self):
        """v1 indent_text: indent selected lines (or the current line)."""
        self.editor.indent_selection()

    # ── outline / TOC panel (M6) ─────────────────────────────────────

    def toggle_outline(self):
        """v1 _toggle_outline: the 目录 toolbar button / panel ✕."""
        self.outline.toggle()

    # ── floating notebook viewers (M6) ───────────────────────────────

    def open_notebook_viewer(self, name):
        """v1 _open_notebook_viewer (L2068): one non-modal editable window
        per notebook; re-opening an already-open one just re-focuses it."""
        viewer = self.viewers.get(name)
        if viewer is not None:
            viewer.raise_()
            viewer.activateWindow()
            return viewer
        viewer = ViewerWindow(self.store, name, self.translator,
                              THEMES[self.theme_name], self.cfg,
                              parent=self)
        viewer.saved.connect(self._on_viewer_saved)
        viewer.closed.connect(self._on_viewer_closed)
        self.viewers[name] = viewer
        viewer.show()
        return viewer

    def _on_viewer_saved(self, name):
        """Explicit viewer save (Cmd+S / close): reload the main editor
        when it shows the same notebook (v1 _reload_current_from_disk)."""
        if name == self.current_notebook:
            self._reload_current_from_disk()

    def _on_viewer_closed(self, name):
        self.viewers.pop(name, None)

    def _reload_current_from_disk(self):
        """v1 _reload_current_from_disk (L2424): re-read notes.txt into
        the main editor, dropping its pending state."""
        self._autosave_timer.stop()
        md = self.marker_doc
        self._loading = True
        try:
            md.load(self.store.load_note_text(self.current_notebook))
        finally:
            self._loading = False
        self._dirty = False
        self._wc_timer.start()
        self.url_previews.rescan()
        self.find_bar.refresh()
        self.outline.update_outline()

    # ── backup restore (M6) ──────────────────────────────────────────

    def show_restore_backup_dialog(self):
        """v1 show_restore_backup_dialog (L3436): list this notebook's
        automatic backups, preview, restore. No backups → alert only."""
        tr = self.translator.tr
        nb = self.current_notebook
        backups = self.store.list_backups(nb)
        if not backups:
            dialogs.show_alert(self, tr, tr("restore_title").format(nb),
                               tr("no_backups"))
            return
        dlg = BackupRestoreDialog(self, tr, nb, backups,
                                  self.store.read_backup,
                                  THEMES[self.theme_name])
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected:
            self._restore_backup(dlg.selected)

    def _restore_backup(self, filename):
        """v1 do_restore: snapshot what is being replaced to backups/
        first, then replace notes.txt and reload the editor."""
        tr = self.translator.tr
        nb = self.current_notebook
        try:
            content = self.store.read_backup(filename)
        except OSError as e:
            dialogs.show_alert(self, tr, tr("warning"), str(e))
            return
        # flush pending editor changes so the snapshot below is complete,
        # then snapshot the current on-disk content (v1 backup_notes)
        self.save_notes(quick=True)
        self.store.backup_note(nb, None)
        self.store.save_note_text(nb, content)
        self._reload_current_from_disk()

    # ── find bar / global search (M5) ────────────────────────────────

    def toggle_find_bar(self):
        """v1 _toggle_search_bar: Cmd/Ctrl+F or the 搜索 button."""
        self.find_bar.toggle_bar()

    def show_global_search(self):
        """v1 show_global_search (L6340)."""
        dlg = GlobalSearchDialog(self, self.translator.tr, self.store,
                                 self.current_notebook,
                                 self.marker_doc.serialize,
                                 THEMES[self.theme_name])
        dlg.open_notebook_at.connect(self._on_global_search_jump)
        dlg.exec()

    def _on_global_search_jump(self, nb, line_no, needle):
        """v1 _global_search_jump (L6555): switch to the notebook, select
        the match on its line, and open the find bar on the query."""
        if nb != self.current_notebook:
            self.switch_notebook(nb)
        block = self._nth_content_block(line_no)
        if block is None:
            return
        cursor = QTextCursor(self.marker_doc.document)
        cursor.setPosition(block.position())
        if needle:
            idx = block.text().lower().find(needle.lower())
            if idx >= 0:
                cursor.setPosition(block.position() + idx)
                cursor.setPosition(block.position() + idx + len(needle),
                                   QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        if self.find_bar.isVisible():
            self.find_bar.refresh()
        else:
            self.find_bar.show_bar()  # prefills from the fresh selection

    def _nth_content_block(self, line_no):
        """The document block for 0-based *content* line *line_no* —
        ephemeral blocks (URL previews, image labels) don't count, since
        search ran over the serialized text."""
        block = self.marker_doc.document.begin()
        n = 0
        while block.isValid():
            if not self.editor._block_is_ephemeral(block):
                if n == line_no:
                    return block
                n += 1
            block = block.next()
        return None

    # ── save selection as notebook / notebook links (M5) ─────────────

    def save_selection_as_notebook(self, content):
        """v1 save_selection_as_notebook (L5294): save the selection's
        marker text into a new notebook (copying referenced attachments)
        and replace the selection with '### name' + [[link]]."""
        tr = self.translator.tr
        if not content.strip():
            return

        def validator(value):
            if value in self.store.list_notebooks():
                return tr("nb_exists")
            return None

        name = dialogs.ask_input(self, tr, tr("save_as_nb_title"),
                                 tr("nb_name_label"),
                                 confirm_text=tr("create"),
                                 validator=validator)
        if not name:
            return
        self.store.create_notebook(name)
        src = self.store.attachments_path(self.current_notebook)
        dst = self.store.attachments_path(name)
        for fname in referenced_attachments(content):
            path = os.path.join(src, fname)
            if os.path.exists(path):
                try:
                    shutil.copy2(path, os.path.join(dst, fname))
                except OSError as e:
                    print(f"Error copying attachment {fname}: {e}")
        self.store.save_note_text(name, content)

        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            start = cursor.selectionStart()
            at_line_start = (self.marker_doc.document.findBlock(start)
                             .position() == start)
            prefix = "" if at_line_start else "\n"
            cursor.beginEditBlock()
            cursor.insertText(f"{prefix}### {name}\n[[{name}]]\n",
                              QTextCharFormat())
            cursor.endEditBlock()
        self._refresh_sidebar()

    def open_notebook_link(self, name):
        """v1 _navigate_to_notebook (L5919): [[name]] switches; missing
        notebooks alert (same English message as v1)."""
        if name in self.store.list_notebooks():
            self.switch_notebook(name)
        else:
            tr = self.translator.tr
            dialogs.show_alert(self, tr, tr("warning"),
                               f"Notebook '{name}' not found.")

    # ── toolbar toggles ──────────────────────────────────────────────

    def _toggle_topmost(self, on):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()  # re-show: changing flags hides the window
        self._schedule_config_save()

    def _toggle_show_image_name(self, _on):
        # marker_doc.config is self.cfg, so future loads pick it up
        self.cfg["show_image_name"] = self.chk_img_name.isChecked()
        self._schedule_config_save()

    def _toggle_recycle_box(self, on):
        self.recycle.setVisible(on)
        self._schedule_config_save()

    def toggle_sidebar(self):
        if self.sidebar_visible:
            w = self.splitter.sizes()[0]
            if w > 1:
                self._sidebar_width = w
            self.sidebar.setVisible(False)
            self.sidebar_visible = False
            self.btn_sidebar.setText("▶")
        else:
            self.sidebar.setVisible(True)
            self.sidebar_visible = True
            self.btn_sidebar.setText("☰")
            self.splitter.setSizes(
                [self._sidebar_width,
                 max(300, self.width() - self._sidebar_width)])
        self._schedule_config_save()

    # ── recycle box / history ────────────────────────────────────────

    def _on_recycle(self, content):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.store.append_history(content, timestamp)

    def show_history(self):
        """v1 show_history: editable history window, saved on close."""
        tr = self.translator.tr
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("history_title"))
        dlg.resize(500, 400)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(5, 5, 5, 5)
        text = QPlainTextEdit(dlg)
        text.setPlainText(self.store.read_history())
        layout.addWidget(text)
        dlg.finished.connect(
            lambda *_: self.store.write_history(text.toPlainText()))
        dlg.exec()

    # ── attachments ──────────────────────────────────────────────────

    def _on_attachment_saved(self, internal, original=None, path=None):
        """attachment_saver hook: persist the filename map (pasted
        screenshots carry no original name and are never mapped, as v1)."""
        if not original:
            return
        self.marker_doc.filename_map[internal] = {"name": original,
                                                  "path": path}
        self.store.ensure_attachments_dir(self.current_notebook)
        self.store.save_filename_map(self.current_notebook,
                                     self.marker_doc.filename_map)

    def cleanup_orphaned_attachments(self):
        """v1 cleanup_orphaned_attachments: remove unreferenced files and
        prune the filename map."""
        content = self.marker_doc.serialize()
        attachments = self.store.attachments_path(self.current_notebook)
        deleted = cleanup_unused(attachments, content)
        mapping = self.marker_doc.filename_map
        changed = False
        for name in list(mapping):
            if (name in deleted
                    or not os.path.exists(os.path.join(attachments, name))):
                del mapping[name]
                changed = True
        if changed:
            self.store.save_filename_map(self.current_notebook, mapping)

    # ── saving ───────────────────────────────────────────────────────

    def _on_content_changed(self):
        # contentsChanged also fires for format-only passes (highlighter
        # work) and for the URL-preview manager's own ephemeral edits;
        # only real user edits flip the document's modified flag.
        if (self._loading or self.url_previews.applying
                or not self.marker_doc.document.isModified()):
            return
        self._dirty = True
        self._autosave_timer.start()
        self._wc_timer.start()
        self.url_previews.schedule()  # debounced re-scan for URL previews

    def save_notes(self, quick=False):
        """Serialize → NoteStore.save_note_text; full saves also snapshot
        the previous on-disk content as a backup on the thread pool (v1
        save_notes/backup_notes)."""
        nb = self.current_notebook
        if quick and not self._dirty:
            return
        if not quick and self.viewers:
            # v1 save_notes L3960-3975: an open viewer of the CURRENT
            # notebook wins — save it and reload the main editor from it
            # (v1 _sync_from_viewer); every other open viewer is saved too.
            viewer = self.viewers.get(nb)
            if viewer is not None:
                viewer.save_now()
                self._reload_current_from_disk()
            for name, other in self.viewers.items():
                if name != nb:
                    other.save_now()
        content = self.marker_doc.serialize()
        store = self.store
        if not quick and os.path.exists(store.note_path(nb)):
            try:
                old_content = store.load_note_text(nb)
                self._pool.start(lambda: store.backup_note(nb, old_content))
            except OSError as e:
                print(f"Error reading notes for backup: {e}")
        try:
            store.save_note_text(nb, content)
            self._dirty = False
            self.marker_doc.document.setModified(False)
        except OSError as e:
            print(f"Error saving notes: {e}")
            tr = self.translator.tr
            dialogs.show_alert(self, tr, tr("warning"),
                               tr("save_failed_msg").format(nb, e))
            return
        # re-sort sidebar: non-pinned notebooks order by mtime (v1)
        self._refresh_sidebar()

    # ── status bar ───────────────────────────────────────────────────

    def _update_status_notebook(self):
        icon = "" if _IS_LINUX else "\U0001f4d3 "
        self.status_nb_label.setText(f"{icon}{self.current_notebook}")

    def _update_word_count(self):
        """v1 _update_word_count (L5982): words (CJK chars count as one
        word each) and chars; selection stats while selecting."""
        cursor = self.editor.textCursor()
        sel = ""
        if cursor.hasSelection():
            # U+2029/U+2028 are Qt's paragraph/line separators; U+FFFC
            # backs image/file objects.
            sel = (cursor.selectedText()
                   .replace("\u2029", "\n").replace("\u2028", "\n")
                   .replace("\ufffc", ""))
        text = sel if sel else strip_markers(self.marker_doc.serialize())
        words = len(_WC_RE.findall(text))
        chars = len(text) - text.count("\n")
        key = "wc_stats_sel" if sel else "wc_stats"
        self.wordcount_label.setText(
            self.translator.tr(key).format(words, chars))

    # ── quit ─────────────────────────────────────────────────────────

    def _confirm_quit(self):
        """v1 _confirm_quit: Cmd+Q asks before quitting."""
        tr = self.translator.tr
        if dialogs.ask_confirm(self, tr, tr("quit_confirm_title"),
                               tr("quit_confirm_msg")):
            self.close()

    def closeEvent(self, event):
        """v1 on_closing: save + destroy the floating viewers first (their
        signals blocked so the sync-back can't clobber the main editor,
        like v1's destroy() skipping the WM_DELETE handler), then save
        everything, wait briefly for the backup thread, and close."""
        self._autosave_timer.stop()
        for viewer in list(self.viewers.values()):
            try:
                viewer.blockSignals(True)
                viewer.close()  # closeEvent saves its content
            except Exception as e:
                print(f"Error closing viewer: {e}")
        self.viewers.clear()
        try:
            self.save_notes()
        except Exception as e:
            print(f"Error saving on close: {e}")
        self._save_config()
        self._pool.waitForDone(3000)
        event.accept()
