import tkinter as tk
from tkinter import ttk
import os
import json
import shutil
import zipfile
import uuid
import re
import subprocess
import platform
import webbrowser
import threading
import urllib.request
import html
from datetime import datetime

try:
    from PIL import Image, ImageTk, ImageGrab, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("Warning: Pillow not installed. Image paste feature disabled. Install with: pip install Pillow")

def _get_system_font():
    """Get the best available system font for the current platform."""
    system = platform.system()
    if system == "Darwin":
        return "SF Pro Text"
    elif system == "Windows":
        return "Segoe UI"
    # Linux: use Helvetica as initial default; will be validated after Tk root
    # is created via _validate_linux_cjk_font() which tests actual rendering.
    return "Helvetica"


def _validate_linux_cjk_font():
    """Find the best CJK-capable font that Tk can actually render on Linux.

    Must be called after a Tk root window exists. Updates the global
    SYSTEM_FONT variable in-place.
    """
    global SYSTEM_FONT
    if platform.system() != "Linux":
        return
    import tkinter.font as tkfont
    # Candidates: fontconfig names first (work when Tk has proper Xft),
    # then X11 core font names (fallback for limited Tk setups).
    candidates = [
        "Noto Sans CJK SC", "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
        "Droid Sans Fallback", "Helvetica", "song ti", "gothic",
    ]
    for name in candidates:
        try:
            f = tkfont.Font(family=name, size=12)
            # A font that can render CJK should give consistent widths for
            # different CJK characters.  A fallback glyph (□) is narrower.
            w1 = f.measure("\u7f6e")  # 置
            w2 = f.measure("\u9876")  # 顶
            if w1 > 0 and abs(w1 - w2) <= 2:
                SYSTEM_FONT = name
                return
        except Exception:
            continue
    SYSTEM_FONT = "Helvetica"

SYSTEM_FONT = _get_system_font()

def _get_mono_font():
    """Get the best available monospace font for the current platform."""
    system = platform.system()
    if system == "Darwin":
        return "Menlo"
    elif system == "Windows":
        return "Consolas"
    return "DejaVu Sans Mono"

MONO_FONT = _get_mono_font()

# Linux X11 bitmap fonts cannot render emoji (U+1F000+) or many extended
# Unicode symbols.  Provide plain-text fallbacks for Linux while keeping
# emoji on macOS / Windows where they render normally.
_IS_LINUX = platform.system() == "Linux"

# ── Internationalisation (i18n) ────────────────────────────────────────
# Each key maps to (Chinese, English).  Use NoteApp.tr(key) at runtime.
_I18N = {
    # Toolbar checkboxes
    "pin_top":          ("置顶", "Pin"),
    "paste_img_name":   ("粘贴图片名", "Img Name"),
    "recycle_box_cb":   ("回收框", "Recycle"),
    # Toolbar buttons (right side, packed RIGHT→LEFT)
    "outline_btn":      ("目录", "TOC"),
    "search_btn":       ("搜索", "Search"),
    "save_btn":         ("保存", "Save"),
    "history_btn":      ("历史", "History"),
    "notebook_btn":     ("笔记本", "Notebook"),
    "icon_btn":         ("图标", "Icon"),
    "ui_size_btn":      ("UI字号", "UI Font"),
    "ui_font_auto":     ("自动适配屏幕", "Auto (fit screen)"),
    "padding_btn":      ("左边距", "Padding"),
    # Sidebar
    "new_btn":          ("+ 新建", "+ New"),
    "manage_btn":       ("管理", "Manage"),
    # Recycle box
    "recycle_title":    ("快速回收框 (Recycle Box)", "Quick Recycle Box"),
    "recycle_btn":      ("回收", "Recycle"),
    # Outline panel
    "outline_title":    ("目录", "Outline"),
    # Icon menu extras
    "refresh_display":  ("刷新显示", "Refresh Display"),
    "clean_attach":     ("清理失效附件", "Clean Orphaned Attachments"),
    # Notebook context menu
    "unpin":            ("★ 取消置顶", "★ Unpin"),
    "pin":              ("☆ 添加置顶", "☆ Pin"),
    "move_up":          ("⬆ 上移", "⬆ Up"),
    "move_down":        ("⬇ 下移", "⬇ Down"),
    "rename_dots":      ("重命名...", "Rename..."),
    "delete":           ("删除", "Delete"),
    # Notebook dropdown menu
    "new_nb_dots":      ("+ 新建笔记本...", "+ New Notebook…"),
    "rename_cur_nb":    ("重命名当前笔记本...", "Rename Notebook…"),
    "delete_cur_nb":    ("删除当前笔记本", "Delete Notebook"),
    "sort_manage":      ("排序管理...", "Sort & Manage…"),
    "export_nb":        ("导出笔记本...", "Export Notebook…"),
    "import_nb":        ("导入笔记本...", "Import Notebook…"),
    "export_ok":        ("笔记本已导出到:\n{}", "Notebook exported to:\n{}"),
    "import_ok":        ("笔记本 '{}' 已导入", "Notebook '{}' imported"),
    "import_err":       ("导入失败: {}", "Import failed: {}"),
    "search_placeholder": ("搜索...", "Search..."),
    "search_n_of_m":    ("{}/{}", "{}/{}"),
    # Text context menu
    "remove_strike":    ("取消删除线", "Remove Strikethrough"),
    "strikethrough":    ("删除线", "Strikethrough"),
    "highlight_menu":   ("高亮", "Highlight"),
    "hl_green":         ("绿色高亮", "Green Highlight"),
    "hl_yellow":        ("黄色高亮", "Yellow Highlight"),
    "hl_red":           ("红色高亮", "Red Highlight"),
    "hl_orange":        ("橙色高亮", "Orange Highlight"),
    "hl_purple":        ("紫色高亮", "Purple Highlight"),
    "remove_highlight": ("取消高亮", "Remove Highlight"),
    "save_as_nb":       ("保存为新的笔记本...", "Save as New Notebook..."),
    "save_as_nb_title": ("保存为新的笔记本", "Save as New Notebook"),
    "copy_nb_link":     ("复制该笔记本链接", "Copy Notebook Link"),
    "nb_viewer_title":  ("笔记本预览", "Notebook Viewer"),
    "open_viewer":      ("在浮动窗口中查看", "Open in Floating Window"),
    # Outline context menu
    "font_larger":      ("字体放大  A+", "Enlarge  A+"),
    "font_smaller":     ("字体缩小  A-", "Shrink  A-"),
    "reset_size":       ("重置大小", "Reset Size"),
    # Image / file context menu
    "copy_link":        ("复制链接 (可在Board内粘贴)", "Copy Link (paste in Board)"),
    "copy_img_file":    ("复制图片/文件", "Copy Image/File"),
    "copy_file_path":   ("复制文件路径", "Copy File Path"),
    "show_in_finder":   ("在 Finder 中显示", "Show in File Manager"),
    "show_original":    ("显示粘贴的原始文件", "Show Original File"),
    "open_default":     ("用默认程序打开", "Open with Default App"),
    "open_file":        ("打开文件", "Open File"),
    "copy_file":        ("复制文件", "Copy File"),
    # Dialog titles
    "history_title":    ("历史记录 (可直接修改)", "History (editable)"),
    "nb_order_title":   ("笔记本排序管理", "Notebook Order"),
    "new_nb_title":     ("新建笔记本", "New Notebook"),
    "rename_nb_title":  ("重命名笔记本", "Rename Notebook"),
    "img_viewer":       ("图片查看", "Image Viewer"),
    # Dialog labels / instructions
    "order_hint":       ("选择笔记本后用 ↑↓ 键或按钮移动位置",
                         "Select a notebook, then use ↑↓ or buttons to reorder"),
    "nb_name_label":    ("笔记本名称:", "Notebook name:"),
    "new_name_label":   ("新名称:", "New name:"),
    # Dialog buttons
    "create":           ("创建", "Create"),
    "rename":           ("重命名", "Rename"),
    "confirm":          ("确定", "OK"),
    "cancel":           ("取消", "Cancel"),
    "up_btn":           ("⬆ 上移", "⬆ Up"),
    "down_btn":         ("⬇ 下移", "⬇ Down"),
    # Message boxes
    "warning":          ("警告", "Warning"),
    "confirm_del":      ("确认删除", "Confirm Delete"),
    "no_rename_def":    ("不能重命名默认笔记本", "Cannot rename the default notebook"),
    "no_delete_def":    ("不能删除默认笔记本", "Cannot delete the default notebook"),
    "nb_exists":        ("笔记本已存在", "Notebook already exists"),
    "confirm_del_msg":  ("确定要删除笔记本 '{}' 吗？\n这将删除所有笔记和附件！",
                         "Delete notebook '{}'?\nAll notes and attachments will be lost!"),
    "quit_confirm_title": ("退出确认", "Confirm Quit"),
    "quit_confirm_msg":   ("确定要退出 Quick Note Board 吗？", "Quit Quick Note Board?"),
    # Language toggle button
    "lang_toggle":      ("EN", "中"),
}

class NoteApp:
    # ── Theme Definitions (Catppuccin-inspired) ──────────────────────────
    THEMES = {
        "dark": {
            "bg":              "#0d1117",
            "bg_secondary":    "#161b22",
            "bg_tertiary":     "#21262d",
            "fg":              "#e6edf3",
            "fg_dim":          "#7d8590",
            "fg_placeholder":  "#484f58",
            "accent":          "#58a6ff",
            "accent_hover":    "#79c0ff",
            "accent_green":    "#3fb950",
            "accent_url":      "#58a6ff",
            "accent_red":      "#f85149",
            "border":          "#30363d",
            "border_light":    "#484f58",
            "button_bg":       "#21262d",
            "button_fg":       "#e6edf3",
            "button_hover":    "#30363d",
            "button_active":   "#484f58",
            "check_bg":        "#21262d",
            "check_fg":        "#e6edf3",
            "check_select":    "#58a6ff",
            "entry_bg":        "#0d1117",
            "entry_fg":        "#e6edf3",
            "entry_border":    "#30363d",
            "combo_bg":        "#0d1117",
            "combo_fg":        "#e6edf3",
            "combo_select_bg": "#30363d",
            "list_bg":         "#0d1117",
            "list_fg":         "#e6edf3",
            "list_select_bg":  "#1f6feb",
            "list_select_fg":  "#ffffff",
            "text_bg":         "#0d1117",
            "text_fg":         "#e6edf3",
            "text_select_bg":  "#1f6feb",
            "text_insert":     "#e6edf3",
            "scrollbar_bg":    "#484f58",
            "scrollbar_trough":"#0d1117",
            "scrollbar_active":"#6e7681",
            "scrollbar_arrow": "#e6edf3",
            "menu_bg":         "#161b22",
            "menu_fg":         "#e6edf3",
            "menu_active_bg":  "#1f6feb",
            "menu_active_fg":  "#ffffff",
            "separator":       "#30363d",
            "paned_sash":      "#30363d",
            "label_frame_fg":  "#7d8590",
            "viewer_toolbar":  "#161b22",
            "viewer_canvas":   "#0d1117",
            "viewer_btn":      "#1f6feb",
            "viewer_btn_hover":"#388bfd",
            "theme_icon":      "\u2600\ufe0f" if not _IS_LINUX else "\u4eae",
            "hl_red":          "#cc3333",
            "hl_yellow":       "#b8a020",
            "hl_orange":       "#cc7520",
            "hl_green":        "#33aa44",
            "hl_purple":       "#8839ef",
        },
        "light": {
            "bg":              "#eff1f5",
            "bg_secondary":    "#e6e9ef",
            "bg_tertiary":     "#dce0e8",
            "fg":              "#4c4f69",
            "fg_dim":          "#8c8fa1",
            "fg_placeholder":  "#9ca0b0",
            "accent":          "#1e66f5",
            "accent_hover":    "#2c78f7",
            "accent_green":    "#40a02b",
            "accent_url":      "#1e66f5",
            "accent_red":      "#d20f39",
            "border":          "#ccd0da",
            "border_light":    "#bcc0cc",
            "button_bg":       "#dce0e8",
            "button_fg":       "#4c4f69",
            "button_hover":    "#ccd0da",
            "button_active":   "#bcc0cc",
            "check_bg":        "#dce0e8",
            "check_fg":        "#4c4f69",
            "check_select":    "#1e66f5",
            "entry_bg":        "#ffffff",
            "entry_fg":        "#4c4f69",
            "entry_border":    "#ccd0da",
            "combo_bg":        "#ffffff",
            "combo_fg":        "#4c4f69",
            "combo_select_bg": "#ccd0da",
            "list_bg":         "#eff1f5",
            "list_fg":         "#4c4f69",
            "list_select_bg":  "#ccd0da",
            "list_select_fg":  "#4c4f69",
            "text_bg":         "#ffffff",
            "text_fg":         "#4c4f69",
            "text_select_bg":  "#ccd0da",
            "text_insert":     "#4c4f69",
            "scrollbar_bg":    "#bcc0cc",
            "scrollbar_trough":"#e6e9ef",
            "scrollbar_active":"#9ca0b0",
            "scrollbar_arrow": "#4c4f69",
            "menu_bg":         "#e6e9ef",
            "menu_fg":         "#4c4f69",
            "menu_active_bg":  "#ccd0da",
            "menu_active_fg":  "#4c4f69",
            "separator":       "#ccd0da",
            "paned_sash":      "#ccd0da",
            "label_frame_fg":  "#6c6f85",
            "viewer_toolbar":  "#dce0e8",
            "viewer_canvas":   "#e6e9ef",
            "viewer_btn":      "#1e66f5",
            "viewer_btn_hover":"#2c78f7",
            "theme_icon":      "\U0001f319" if not _IS_LINUX else "\u6697",
            "hl_red":          "#ff3333",
            "hl_yellow":       "#e6c800",
            "hl_orange":       "#ff8c00",
            "hl_green":        "#22bb44",
            "hl_purple":       "#a855f7",
        },
    }

    HIGHLIGHT_NAMES = ("green", "yellow", "red", "orange", "purple")

    def __init__(self, root):
        self.root = root
        self.root.title("Quick Note Board")
        self.root.geometry("400x300")

        # Theme state (default dark, will be overridden by config)
        self.current_theme = "dark"
        self.current_theme_colors = self.THEMES["dark"]

        # Language state (default Chinese, will be overridden by config)
        self.language = "zh"

        # Set window icon
        self.set_window_icon()

        # Notebooks directory
        self.notebooks_dir = "notebooks"
        self.ensure_notebooks_dir()
        self.current_notebook = "默认"  # Will be loaded from config
        self.previous_notebook = None  # 上一个选中的笔记本，用于快速切换

        self.note_file = "notes.txt"
        self.config_file = "config.json"
        self.notebook_order_file = "notebook_order.json"  # 笔记本顺序配置
        self.history_file = "history.txt" # Changed to .txt for easier editing
        self.json_history_file = "history.json" # Keep track of old file for migration
        self.current_font_size = 12
        self.notebook_order = []  # 笔记本顺序列表
        self.notebook_shortcuts = []  # 快捷方式笔记本列表

        # Attachments directory for images and files
        self.attachments_dir = "attachments"
        self.ensure_attachments_dir()

        # Store image references to prevent garbage collection
        self.images = {}

        # In-memory cache for video thumbnails (internal_filename -> PIL Image)
        self._video_thumb_cache = {}

        # Store custom width for each image (internal_filename -> width)
        self.image_widths = {}

        # Store resize drag state
        self.image_resize_state = None  # {filename, start_x, start_width, image_id}

        # Store pending click action (for distinguishing single vs double click)
        self._pending_click_id = None

        # Throttle for motion events to reduce CPU usage
        self._last_motion_time = 0
        self._motion_throttle_ms = 50  # Only process motion events every 50ms

        # Store copied file/image link for internal paste
        self.copied_internal_link = None  # (type, internal_filename) e.g. ("file", "xxx.mp4") or ("image", "xxx.png")

        # Map internal filename to original filename
        self.filename_map = {}  # internal_name -> original_name
        self.load_filename_map()

        # Image settings - available sizes
        self.image_sizes = [100, 200, 300, 400, 500, 600]
        self.max_image_width = 400  # default, will be loaded from config

        # File icon size
        self.icon_sizes = [16, 20, 24, 32, 40, 48]
        self.icon_font_size = 24  # default icon size

        # UI font size (toolbar, sidebar, dialogs)
        self.ui_font_sizes = [11, 12, 13, 14, 15, 16, 18, 20]
        # Auto-pick a comfortable default from the screen size (config may override)
        self.ui_font_size = self._auto_ui_font_size()

        # Text area padding
        self.padding_sizes = [0, 5, 10, 15, 20, 30, 40]
        self.text_padding = 10  # default padding

        # URL pattern for detecting links
        self.url_pattern = re.compile(
            r'(https?://[^\s<>"{}|\\^`\[\]]+)',
            re.IGNORECASE
        )
        # Track URL tags for cleanup
        self.url_tags = set()

        # URL title preview: cache, preview tags, and pending fetches
        self._url_title_cache = {}       # URL -> title string
        self._url_preview_tags = set()   # set of "url_preview_N" tag names
        self._url_fetch_pending = set()  # URLs currently being fetched
        self._load_url_title_cache()

        # Custom undo/redo stack for better image support
        self.undo_stack = []
        self.redo_stack = []
        self.max_undo_levels = 50
        self.is_restoring = False  # Flag to prevent saving state during restore

        # Markdown rendering debounce timer
        self._md_update_timer_id = None
        self._md_active_line = None        # line with cursor (markers visible)
        self._md_marker_ranges = {}        # {line_num: [(start, end), ...]}

        # Floating notebook viewers
        self._notebook_viewers = []

        # Outline panel state
        self._outline_visible = False
        self._outline_headings = []        # [(line_num, level, text), ...]
        self._outline_width = 240          # default width, persisted in config
        self._outline_height = 0           # 0 = auto-fit, >0 = user-set, persisted
        self._outline_font_size = 12       # base font size for outline, persisted

        # Migrate old history if needed
        self.migrate_history()

        # 变量，用于存储Checkbox的状态
        self.always_on_top = tk.BooleanVar()
        self.show_image_name = tk.BooleanVar(value=True)  # 是否显示粘贴图片的文件名
        self.show_recycle_box = tk.BooleanVar(value=True)  # 是否显示快速回收框
        self.sidebar_visible = True  # 侧边栏是否显示
        self.content_modified = False  # 内容是否被修改，用于快速切换时跳过保存

        # Validate CJK font on Linux (must happen after Tk root exists)
        _validate_linux_cjk_font()

        # Initialize ttk styles
        self.setup_ttk_styles()

        # 创建顶部框架
        self.top_frame = tk.Frame(root)
        self.top_frame.pack(fill=tk.X, padx=5, pady=(5, 2))

        # Checkboxes (ttk)
        self.check_btn = ttk.Checkbutton(
            self.top_frame, text=self.tr("pin_top"), variable=self.always_on_top,
            command=self.toggle_topmost, style="Toolbar.TCheckbutton"
        )
        self.check_btn.pack(side=tk.LEFT)

        self.image_name_btn = ttk.Checkbutton(
            self.top_frame, text=self.tr("paste_img_name"), variable=self.show_image_name,
            style="Toolbar.TCheckbutton"
        )
        self.image_name_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.recycle_box_btn = ttk.Checkbutton(
            self.top_frame, text=self.tr("recycle_box_cb"), variable=self.show_recycle_box,
            command=self.toggle_recycle_box, style="Toolbar.TCheckbutton"
        )
        self.recycle_box_btn.pack(side=tk.LEFT, padx=(8, 0))

        # Separator
        ttk.Separator(self.top_frame, orient=tk.VERTICAL, style="Toolbar.TSeparator").pack(
            side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        # 侧边栏切换按钮
        self.sidebar_toggle_btn = ttk.Button(
            self.top_frame, text="\u2630", command=self.toggle_sidebar,
            style="Toolbar.TButton", width=3)
        self.sidebar_toggle_btn.pack(side=tk.LEFT)

        # 笔记本当前选中状态（侧边栏列表负责切换；不再显示顶部下拉框）
        self.notebook_var = tk.StringVar(value=self.current_notebook)

        # 功能按钮组（移到左侧，紧跟侧边栏开关之后）
        font_btn_frame = tk.Frame(self.top_frame)
        font_btn_frame.pack(side=tk.LEFT, padx=(12, 0))

        # Theme toggle button (rightmost)
        self.theme_toggle_btn = ttk.Button(
            font_btn_frame, text=self.current_theme_colors["theme_icon"],
            command=self.toggle_theme, style="Toolbar.TButton", width=3)
        self.theme_toggle_btn.pack(side=tk.RIGHT, padx=2)

        # Language toggle button
        self._btn_lang = ttk.Button(
            font_btn_frame, text=self.tr("lang_toggle"),
            command=self._switch_language, style="Toolbar.TButton", width=3)
        self._btn_lang.pack(side=tk.RIGHT, padx=2)

        ttk.Separator(font_btn_frame, orient=tk.VERTICAL, style="Toolbar.TSeparator").pack(
            side=tk.RIGHT, fill=tk.Y, padx=4, pady=2)

        ttk.Button(font_btn_frame, text="A+", command=self.increase_font,
                   style="Toolbar.TButton", width=3).pack(side=tk.RIGHT, padx=1)
        ttk.Button(font_btn_frame, text="A-", command=self.decrease_font,
                   style="Toolbar.TButton", width=3).pack(side=tk.RIGHT, padx=1)
        ttk.Button(font_btn_frame, text="\u2192", command=self.indent_text,
                   style="Toolbar.TButton", width=2).pack(side=tk.RIGHT, padx=1)

        ttk.Separator(font_btn_frame, orient=tk.VERTICAL, style="Toolbar.TSeparator").pack(
            side=tk.RIGHT, fill=tk.Y, padx=4, pady=2)

        self._btn_padding = ttk.Button(font_btn_frame, text=self.tr("padding_btn"),
                   command=self.show_padding_menu, style="Toolbar.TButton", width=5)
        self._btn_padding.pack(side=tk.RIGHT, padx=1)
        self._btn_ui_size = ttk.Button(font_btn_frame, text=self._ui_size_btn_label(),
                   command=self.show_ui_font_menu, style="Toolbar.TButton", width=8)
        self._btn_ui_size.pack(side=tk.RIGHT, padx=1)
        self._btn_icon = ttk.Button(font_btn_frame, text=self.tr("icon_btn"),
                   command=self.show_icon_menu, style="Toolbar.TButton", width=4)
        self._btn_icon.pack(side=tk.RIGHT, padx=1)
        self._btn_notebook = ttk.Button(font_btn_frame, text=self.tr("notebook_btn"),
                   command=self.show_notebook_menu, style="Toolbar.TButton", width=5)
        self._btn_notebook.pack(side=tk.RIGHT, padx=1)
        self._btn_history = ttk.Button(font_btn_frame, text=self.tr("history_btn"),
                   command=self.show_history, style="Toolbar.TButton", width=4)
        self._btn_history.pack(side=tk.RIGHT, padx=1)
        self._btn_save = ttk.Button(font_btn_frame, text=self.tr("save_btn"),
                   command=self.save_notes, style="Toolbar.TButton", width=4)
        self._btn_save.pack(side=tk.RIGHT, padx=1)
        self._btn_outline = ttk.Button(font_btn_frame, text=self.tr("outline_btn"),
                   command=self._toggle_outline, style="Toolbar.TButton", width=4)
        self._btn_outline.pack(side=tk.RIGHT, padx=1)
        self._btn_search = ttk.Button(font_btn_frame, text=self.tr("search_btn"),
                   command=self._toggle_search_bar, style="Toolbar.TButton", width=4)
        self._btn_search.pack(side=tk.RIGHT, padx=1)

        # --- 主内容区域：左侧侧边栏 + 右侧内容 ---
        t = self.current_theme_colors
        self.main_paned = tk.PanedWindow(root, orient=tk.HORIZONTAL, sashwidth=8,
                                          sashrelief=tk.RAISED, sashpad=0,
                                          opaqueresize=True, bg=t["paned_sash"])
        self.main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # === 左侧侧边栏：笔记本列表 ===
        self._sidebar_width = 150  # 记住用户拖拽设置的宽度（load_config 会覆盖）
        self.sidebar_frame = tk.Frame(self.main_paned, width=self._sidebar_width, bg=t["bg"])
        self.sidebar_frame.pack_propagate(False)

        # 搜索框
        search_frame = tk.Frame(self.sidebar_frame, bg=t["bg"])
        search_frame.pack(fill=tk.X, padx=5, pady=5)
        _search_icon = "\U0001f50d" if not _IS_LINUX else "\u641c"
        tk.Label(search_frame, text=_search_icon, bg=t["bg"], fg=t["fg"]).pack(side=tk.LEFT)
        self.notebook_search_var = tk.StringVar()
        self.notebook_search_var.trace_add("write", self.on_notebook_search_changed)
        self.notebook_search_entry = ttk.Entry(search_frame, textvariable=self.notebook_search_var,
                                                width=15, style="Sidebar.TEntry")
        self.notebook_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

        # 笔记本列表
        list_frame = tk.Frame(self.sidebar_frame, bg=t["bg"])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        self.notebook_listbox = ttk.Treeview(
            list_frame, show="tree", selectmode="browse",
            style="Sidebar.Treeview")
        self.notebook_listbox.column("#0", width=120, stretch=True)
        notebook_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                            command=self.notebook_listbox.yview,
                                            style="Visible.Vertical.TScrollbar")
        self.notebook_listbox.config(yscrollcommand=notebook_scrollbar.set)

        notebook_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.notebook_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.notebook_listbox.bind("<<TreeviewSelect>>", self.on_notebook_listbox_select)
        self.notebook_listbox.bind("<Double-Button-1>", self.on_notebook_listbox_double_click)
        self.notebook_listbox.bind("<Button-2>", self.on_notebook_listbox_right_click)  # macOS
        self.notebook_listbox.bind("<Button-3>", self.on_notebook_listbox_right_click)  # Windows/Linux
        # Drag-and-drop reordering
        self._drag_start_iid = None
        self._drag_active = False
        self.notebook_listbox.bind("<Button-1>", self._on_listbox_drag_start)
        self.notebook_listbox.bind("<B1-Motion>", self._on_listbox_drag_motion)
        self.notebook_listbox.bind("<ButtonRelease-1>", self._on_listbox_drag_end)

        # 底部按钮区域
        sidebar_btn_frame = tk.Frame(self.sidebar_frame, bg=t["bg"])
        sidebar_btn_frame.pack(fill=tk.X, padx=5, pady=5)

        self._btn_new = ttk.Button(sidebar_btn_frame, text=self.tr("new_btn"),
                   command=self.create_notebook, style="Sidebar.TButton")
        self._btn_new.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._btn_manage = ttk.Button(sidebar_btn_frame, text=self.tr("manage_btn"),
                   command=self.show_notebook_order_dialog, style="Sidebar.TButton")
        self._btn_manage.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

        self.main_paned.add(self.sidebar_frame, minsize=120)

        # === 右侧内容区域 ===
        self.right_content = tk.Frame(self.main_paned, bg=t["bg"])

        # --- 回收框区域 ---
        self.recycle_frame = tk.LabelFrame(
            self.right_content, text=self.tr("recycle_title"),
            padx=5, pady=5, bg=t["bg"], fg=t["label_frame_fg"],
            font=(SYSTEM_FONT, self.ui_font_size))
        self.recycle_frame.pack(fill=tk.X, padx=0, pady=0)

        self.recycle_text = tk.Text(
            self.recycle_frame, height=3, font=(SYSTEM_FONT, self.ui_font_size),
            bg=t["text_bg"], fg=t["text_fg"], insertbackground=t["text_insert"],
            selectbackground=t["text_select_bg"], relief=tk.FLAT,
            highlightthickness=1, highlightcolor=t["border"],
            highlightbackground=t["border"])
        self.recycle_text.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._btn_recycle = ttk.Button(self.recycle_frame, text=self.tr("recycle_btn"),
                   command=self.recycle_note, style="Toolbar.TButton")
        self._btn_recycle.pack(side=tk.LEFT, padx=5)

        # 文本区域容器 (包含文本和滚动条)
        self.text_container = tk.Frame(self.right_content, bg=t["bg"])
        self.text_container.pack(fill=tk.BOTH, expand=True, pady=5)

        # 文本区域 (Main Note Area) - 启用撤销功能
        _sp1, _sp2, _sp3 = self._line_spacing(self.current_font_size)
        self.text_area = tk.Text(
            self.text_container, wrap=tk.WORD,
            font=(SYSTEM_FONT, self.current_font_size), undo=True,
            padx=self.text_padding,
            spacing1=_sp1, spacing2=_sp2, spacing3=_sp3,
            bg=t["text_bg"], fg=t["text_fg"],
            insertbackground=t["text_insert"],
            selectbackground=t["text_select_bg"],
            relief=tk.FLAT, highlightthickness=0)

        # 创建醒目的滚动条
        scrollbar = ttk.Scrollbar(
            self.text_container, orient=tk.VERTICAL,
            command=self.text_area.yview,
            style="Visible.Vertical.TScrollbar"
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_text_scroll(*args):
            scrollbar.set(*args)
            if hasattr(self, 'outline_text') and self._outline_visible:
                self._update_outline_from_scroll()
        self.text_area.config(yscrollcommand=_on_text_scroll)
        self.text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Search bar state (built lazily on first Cmd+F)
        self._search_visible = False
        self._search_matches = []
        self._search_current_idx = -1

        # Build floating outline panel (table of contents)
        self._build_outline_panel()

        self.main_paned.add(self.right_content, minsize=300)

        # Bind paste event for images and files
        self.setup_paste_binding()

        # Bind undo/redo
        self.setup_undo_redo()

        # Configure strikethrough tag and right-click context menu
        self.setup_strikethrough()

        # Configure Markdown rendering tags
        self.setup_markdown_tags()

        # 加载配置（包括当前笔记本）
        self.load_config()

        # 加载笔记
        self.load_notes()

        # 初始化侧边栏笔记本列表
        self.refresh_notebook_listbox()

        # 恢复目录面板可见状态
        if getattr(self, '_outline_restore', False):
            self._toggle_outline()

        # 绑定关闭事件以保存笔记
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Cmd+Q 二次确认（避免误触退出，丢失未保存内容）
        if platform.system() == "Darwin":
            try:
                # 拦截系统级 Quit（Apple 菜单 → Quit、以及大多数 Cmd+Q 路径）
                self.root.createcommand("::tk::mac::Quit", self._confirm_quit)
            except Exception:
                pass
        # 直接绑定 Cmd+Q / Ctrl+Q 作为兜底
        self.root.bind_all("<Command-q>", self._confirm_quit)
        self.root.bind_all("<Command-Q>", self._confirm_quit)
        self.root.bind_all("<Control-q>", self._confirm_quit)
        self.root.bind_all("<Control-Q>", self._confirm_quit)

    def toggle_topmost(self):
        is_top = self.always_on_top.get()
        # macOS和Windows都支持 -topmost
        self.root.wm_attributes("-topmost", 1 if is_top else 0)

    # ── Theme Infrastructure ─────────────────────────────────────────────
    def setup_ttk_styles(self):
        """Configure ttk styles for the current theme."""
        t = self.current_theme_colors
        uf = self.ui_font_size
        s = ttk.Style()
        s.theme_use("clam")

        # ── TButton ──
        s.configure("Toolbar.TButton",
                     background=t["button_bg"], foreground=t["button_fg"],
                     borderwidth=0, padding=(8, 4), font=(SYSTEM_FONT, uf))
        s.map("Toolbar.TButton",
              background=[("active", t["button_hover"]), ("pressed", t["button_active"])],
              foreground=[("disabled", t["fg_dim"])])

        # ── TCheckbutton ──
        s.configure("Toolbar.TCheckbutton",
                     background=t["bg_secondary"], foreground=t["check_fg"],
                     indicatorbackground=t["check_bg"], indicatorforeground=t["check_select"],
                     font=(SYSTEM_FONT, uf))
        s.map("Toolbar.TCheckbutton",
              background=[("active", t["bg_secondary"])],
              indicatorbackground=[("selected", t["check_select"])])

        # ── Sidebar TEntry ──
        s.configure("Sidebar.TEntry",
                     fieldbackground=t["entry_bg"], foreground=t["entry_fg"],
                     bordercolor=t["entry_border"], insertcolor=t["text_insert"],
                     font=(SYSTEM_FONT, uf))

        # ── TCombobox ──
        s.configure("TCombobox",
                     fieldbackground=t["combo_bg"], foreground=t["combo_fg"],
                     background=t["button_bg"], arrowcolor=t["fg"],
                     bordercolor=t["border"], selectbackground=t["combo_select_bg"],
                     selectforeground=t["combo_fg"],
                     font=(SYSTEM_FONT, uf))
        s.map("TCombobox",
              fieldbackground=[("readonly", t["combo_bg"])],
              foreground=[("readonly", t["combo_fg"])],
              selectbackground=[("readonly", t["combo_select_bg"])],
              selectforeground=[("readonly", t["combo_fg"])])
        # Style the dropdown listbox
        self.root.option_add("*TCombobox*Listbox.background", t["combo_bg"])
        self.root.option_add("*TCombobox*Listbox.foreground", t["combo_fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", t["combo_select_bg"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", t["combo_fg"])

        # ── TScrollbar ──
        s.configure("Visible.Vertical.TScrollbar",
                     background=t["scrollbar_bg"], troughcolor=t["scrollbar_trough"],
                     bordercolor=t["scrollbar_trough"], arrowcolor=t["scrollbar_arrow"],
                     lightcolor=t["scrollbar_bg"], darkcolor=t["scrollbar_bg"])
        s.map("Visible.Vertical.TScrollbar",
              background=[("active", t["scrollbar_active"]), ("pressed", t["scrollbar_active"])],
              arrowcolor=[("active", t["scrollbar_arrow"])])

        # ── TSeparator ──
        s.configure("Toolbar.TSeparator", background=t["separator"])

        # ── Sidebar TButton ──
        s.configure("Sidebar.TButton",
                     background=t["button_bg"], foreground=t["button_fg"],
                     borderwidth=0, padding=(6, 3), font=(SYSTEM_FONT, uf))
        s.map("Sidebar.TButton",
              background=[("active", t["button_hover"]), ("pressed", t["button_active"])])

        # ── Sidebar Treeview (notebook list) ──
        # rowheight gives each entry vertical breathing room (Listbox can't)
        row_h = max(int(uf * 2.0), uf + 12)
        s.configure("Sidebar.Treeview",
                     background=t["list_bg"], fieldbackground=t["list_bg"],
                     foreground=t["list_fg"], borderwidth=0, relief="flat",
                     rowheight=row_h, indent=10, font=(SYSTEM_FONT, uf))
        s.map("Sidebar.Treeview",
              background=[("selected", t["list_select_bg"])],
              foreground=[("selected", t["list_select_fg"])])
        # Drop the default border element so the tree blends into the sidebar
        s.layout("Sidebar.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    def apply_theme(self, theme_name):
        """Apply a theme by name, updating all widgets."""
        self.current_theme = theme_name
        self.current_theme_colors = self.THEMES[theme_name]
        t = self.current_theme_colors

        # Reconfigure ttk styles
        self.setup_ttk_styles()

        # Root window
        self.root.configure(bg=t["bg"])

        # Top frame and all child frames
        if hasattr(self, 'top_frame'):
            self._theme_frame_children(self.top_frame, t["bg_secondary"])

        # Sidebar
        if hasattr(self, 'sidebar_frame'):
            self._theme_frame_children(self.sidebar_frame, t["bg"])
        # Notebook list colors/rowheight are driven by the "Sidebar.Treeview"
        # ttk style, already refreshed via setup_ttk_styles() above.

        # Main paned window
        if hasattr(self, 'main_paned'):
            self.main_paned.configure(bg=t["paned_sash"], sashrelief=tk.RAISED)

        # Text area
        if hasattr(self, 'text_area'):
            self.text_area.configure(
                bg=t["text_bg"], fg=t["text_fg"],
                insertbackground=t["text_insert"],
                selectbackground=t["text_select_bg"],
                relief=tk.FLAT, highlightthickness=0,
                font=(SYSTEM_FONT, self.current_font_size))

        # Recycle box
        if hasattr(self, 'recycle_frame'):
            self.recycle_frame.configure(
                bg=t["bg"], fg=t["label_frame_fg"],
                font=(SYSTEM_FONT, self.ui_font_size))
        if hasattr(self, 'recycle_text'):
            self.recycle_text.configure(
                bg=t["text_bg"], fg=t["text_fg"],
                insertbackground=t["text_insert"],
                selectbackground=t["text_select_bg"],
                relief=tk.FLAT, highlightthickness=1, highlightcolor=t["border"],
                highlightbackground=t["border"],
                font=(SYSTEM_FONT, self.ui_font_size))

        # Right content frame
        if hasattr(self, 'right_content'):
            self._theme_frame_children(self.right_content, t["bg"])
        if hasattr(self, 'text_container'):
            self.text_container.configure(bg=t["bg"])

        # Update text tags
        self._update_text_tags()

        # Update theme toggle button text
        if hasattr(self, 'theme_toggle_btn'):
            self.theme_toggle_btn.configure(text=t["theme_icon"])

        # Keep the UI-font button label in sync with the actual current size
        if hasattr(self, '_btn_ui_size'):
            self._btn_ui_size.configure(text=self._ui_size_btn_label())

        # Search bar
        if hasattr(self, '_search_frame'):
            self._search_frame.configure(bg=t["bg_secondary"], highlightbackground=t["border"])
            for child in self._search_frame.winfo_children():
                if isinstance(child, tk.Frame):
                    child.configure(bg=t["bg_secondary"])
            self._search_entry.configure(bg=t["entry_bg"], fg=t["entry_fg"],
                                          insertbackground=t["text_insert"],
                                          highlightcolor=t["accent"],
                                          highlightbackground=t["border"])
            self._search_count_label.configure(bg=t["bg_secondary"], fg=t["fg_dim"])
            for btn in (self._search_prev_btn, self._search_next_btn, self._search_close_btn):
                btn.configure(bg=t["bg_secondary"], fg=t["fg_dim"])
            self.text_area.tag_configure("search_match",
                                          background=t["accent"] if self.current_theme == "dark" else "#b4d5fe",
                                          foreground="#ffffff" if self.current_theme == "dark" else "#1e1e2e")
            self.text_area.tag_configure("search_current",
                                          background="#f0a020", foreground="#1e1e2e")

        # Outline panel
        if hasattr(self, 'outline_frame'):
            self.outline_frame.configure(bg=t["bg_secondary"],
                                         highlightbackground=t["border"])
            self.outline_title.configure(bg=t["bg_secondary"], fg=t["fg_dim"])
            self.outline_close_btn.configure(bg=t["bg_secondary"], fg=t["fg_dim"])
            self._outline_drag_handle.configure(bg=t["bg_secondary"])
            self._outline_bottom_handle.configure(bg=t["bg_secondary"])
            # Rebind hover colors for new theme
            self._outline_drag_handle.bind("<Enter>", lambda e: self._outline_drag_handle.configure(bg=t["border"]))
            self._outline_drag_handle.bind("<Leave>", lambda e: self._outline_drag_handle.configure(bg=t["bg_secondary"]))
            self._outline_bottom_handle.bind("<Enter>", lambda e: self._outline_bottom_handle.configure(bg=t["border"]))
            self._outline_bottom_handle.bind("<Leave>", lambda e: self._outline_bottom_handle.configure(bg=t["bg_secondary"]))
            # Theme the title bar frame
            for w in self.outline_frame.winfo_children():
                if isinstance(w, tk.Frame) and w != self._outline_drag_handle:
                    w.configure(bg=t["bg_secondary"])
                    for child in w.winfo_children():
                        if isinstance(child, tk.Frame):
                            child.configure(bg=t["bg_secondary"])
            self.outline_text.configure(bg=t["bg_secondary"], fg=t["fg"])
            self.outline_text.tag_configure("ol_h1", foreground=t["fg"])
            self.outline_text.tag_configure("ol_h2", foreground=t["fg"])
            self.outline_text.tag_configure("ol_h3", foreground=t["fg_dim"])
            self.outline_text.tag_configure("ol_hover", background=t["bg_tertiary"])
            self.outline_text.tag_configure("ol_active", foreground=t["accent"])
            for color in self.HIGHLIGHT_NAMES:
                # Highlighted headings get a thin colored left bar (a colored
                # glyph), not a full text-background fill — keeps a clean,
                # aligned right edge in the outline.
                self.outline_text.tag_configure(f"ol_bar_{color}", foreground=t[f"hl_{color}"])
            self.outline_text.tag_configure("ol_bar_none", foreground=t["bg_secondary"])
            self.text_area.tag_configure("outline_flash", background=t["list_select_bg"])

    # ── Internationalisation helpers ──────────────────────────────────────

    def tr(self, key):
        """Return the translated string for *key* in the current language."""
        zh, en = _I18N.get(key, (key, key))
        return zh if self.language == "zh" else en

    def _switch_language(self):
        """Toggle between Chinese and English UI and refresh all text."""
        self.language = "en" if self.language == "zh" else "zh"
        self._refresh_all_text()
        self.save_config()

    def _refresh_all_text(self):
        """Update every user-visible string to match self.language."""
        # Toolbar checkboxes
        self.check_btn.configure(text=self.tr("pin_top"))
        self.image_name_btn.configure(text=self.tr("paste_img_name"))
        self.recycle_box_btn.configure(text=self.tr("recycle_box_cb"))
        # Toolbar buttons
        self._btn_outline.configure(text=self.tr("outline_btn"))
        self._btn_search.configure(text=self.tr("search_btn"))
        self._btn_save.configure(text=self.tr("save_btn"))
        self._btn_history.configure(text=self.tr("history_btn"))
        self._btn_notebook.configure(text=self.tr("notebook_btn"))
        self._btn_icon.configure(text=self.tr("icon_btn"))
        self._btn_ui_size.configure(text=self._ui_size_btn_label())
        self._btn_padding.configure(text=self.tr("padding_btn"))
        self._btn_lang.configure(text=self.tr("lang_toggle"))
        # Sidebar
        self._btn_new.configure(text=self.tr("new_btn"))
        self._btn_manage.configure(text=self.tr("manage_btn"))
        # Recycle box
        self.recycle_frame.configure(text=self.tr("recycle_title"))
        self._btn_recycle.configure(text=self.tr("recycle_btn"))
        # Outline panel (if created)
        if hasattr(self, "outline_title"):
            self.outline_title.configure(text=self.tr("outline_title"))

    def toggle_theme(self):
        """Switch between dark and light themes."""
        new_theme = "light" if self.current_theme == "dark" else "dark"
        self.apply_theme(new_theme)
        self.save_config()

    def make_styled_menu(self, parent=None):
        """Create a Menu widget styled for the current theme."""
        t = self.current_theme_colors
        if parent is None:
            parent = self.root
        return tk.Menu(parent, tearoff=0,
                       bg=t["menu_bg"], fg=t["menu_fg"],
                       activebackground=t["menu_active_bg"],
                       activeforeground=t["menu_active_fg"],
                       relief=tk.FLAT, borderwidth=1)

    def _theme_frame_children(self, frame, bg_color):
        """Recursively set background on Frame/Label children."""
        try:
            frame.configure(bg=bg_color)
        except tk.TclError:
            pass
        for child in frame.winfo_children():
            widget_class = child.winfo_class()
            if widget_class in ("Frame", "Label", "Labelframe"):
                try:
                    child.configure(bg=bg_color)
                except tk.TclError:
                    pass
                self._theme_frame_children(child, bg_color)

    def _update_text_tags(self):
        """Update text tag colors to match current theme."""
        t = self.current_theme_colors
        # Strikethrough
        try:
            self.text_area.tag_configure("strikethrough",
                                         overstrike=True, foreground=t["fg_dim"])
        except:
            pass
        # Highlight colors. spacing1/spacing3=0 so the colored block hugs the
        # text instead of extending into the inter-line spacing above/below.
        for color in self.HIGHLIGHT_NAMES:
            try:
                self.text_area.tag_configure(f"highlight_{color}",
                                             background=t[f"hl_{color}"],
                                             spacing1=0, spacing3=0)
            except:
                pass
        # File link tags
        for tag in self.text_area.tag_names():
            try:
                if tag.startswith("file_"):
                    self.text_area.tag_config(tag, foreground=t["accent_green"])
                elif tag.startswith("imgname_"):
                    self.text_area.tag_config(tag, foreground=t["fg_dim"])
                elif tag.startswith("url_preview_"):
                    self.text_area.tag_config(tag, foreground=t["fg_dim"])
                elif tag.startswith("nb_link_"):
                    self.text_area.tag_config(tag, foreground=t["accent_url"], underline=True)
                elif tag.startswith("url_"):
                    self.text_area.tag_config(tag, foreground=t["accent_url"])
                elif tag.startswith("icon_"):
                    self.text_area.tag_config(tag, font=(SYSTEM_FONT, self.icon_font_size))
            except:
                pass
        # Update markdown tag styles
        self._update_markdown_tag_styles()

    def toggle_sidebar(self):
        """Toggle sidebar visibility"""
        if self.sidebar_visible:
            # Hide sidebar
            self.main_paned.forget(self.sidebar_frame)
            self.sidebar_visible = False
            self.sidebar_toggle_btn.config(text="▶")
        else:
            # Show sidebar
            self.main_paned.add(self.sidebar_frame, before=self.main_paned.panes()[0],
                                minsize=120, width=getattr(self, '_sidebar_width', 150))
            self.sidebar_visible = True
            self.sidebar_toggle_btn.config(text="☰")
            self.highlight_current_notebook()
        self.save_config()

    def toggle_recycle_box(self):
        """Toggle recycle box visibility"""
        if self.show_recycle_box.get():
            self.recycle_frame.pack(fill=tk.X, padx=0, pady=0, before=self.text_container)
        else:
            self.recycle_frame.pack_forget()
        self.save_config()

    def migrate_history(self):
        # If json exists but txt doesn't, migrate content
        if os.path.exists(self.json_history_file) and not os.path.exists(self.history_file):
            try:
                with open(self.json_history_file, "r", encoding="utf-8") as f:
                    history_data = json.load(f)
                
                with open(self.history_file, "w", encoding="utf-8") as f:
                    for item in history_data:
                        f.write(f"--- {item['timestamp']} ---\n")
                        f.write(f"{item['content']}\n\n")
                
                # Optional: Remove old file or rename it
                # os.remove(self.json_history_file) 
                print("Migrated history.json to history.txt")
            except Exception as e:
                print(f"Error migrating history: {e}")

    def recycle_note(self):
        # Get content from the NEW recycle text box
        content = self.recycle_text.get("1.0", "end-1c").strip()
        if not content:
            return

        # Prepare new entry
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_entry = f"--- {timestamp} ---\n{content}\n\n"

        # Prepend to history file (read existing, write new + existing)
        existing_content = ""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    existing_content = f.read()
            except Exception as e:
                print(f"Error reading history: {e}")

        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                f.write(new_entry + existing_content)
        except Exception as e:
            print(f"Error saving history: {e}")

        # Clear recycle text box
        self.recycle_text.delete("1.0", tk.END)

    def show_history(self):
        t = self.current_theme_colors
        history_window = tk.Toplevel(self.root)
        history_window.title(self.tr("history_title"))
        history_window.geometry("500x400")
        history_window.configure(bg=t["bg"])

        # Ensure history window is also topmost if main window is
        if self.always_on_top.get():
            history_window.wm_attributes("-topmost", 1)

        text_widget = tk.Text(history_window, wrap=tk.WORD, font=(SYSTEM_FONT, self.ui_font_size),
                              bg=t["text_bg"], fg=t["text_fg"],
                              insertbackground=t["text_insert"],
                              selectbackground=t["text_select_bg"],
                              relief=tk.FLAT, highlightthickness=0)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Load history content
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    text_widget.insert(tk.END, content)
            except Exception as e:
                text_widget.insert(tk.END, f"Error loading history: {e}")
        else:
            text_widget.insert(tk.END, "")

        # Save on close
        def on_history_close():
            try:
                content = text_widget.get("1.0", "end-1c")
                with open(self.history_file, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                print(f"Error saving history on close: {e}")
            history_window.destroy()

        history_window.protocol("WM_DELETE_WINDOW", on_history_close)

    def _line_spacing(self, font_size):
        """Comfortable (above, between-wrapped, below) line spacing for a font size."""
        return (max(2, int(font_size * 0.30)),
                max(2, int(font_size * 0.30)),
                max(3, int(font_size * 0.55)))

    def update_font(self):
        sp1, sp2, sp3 = self._line_spacing(self.current_font_size)
        self.text_area.configure(font=(SYSTEM_FONT, self.current_font_size),
                                 spacing1=sp1, spacing2=sp2, spacing3=sp3)
        self._update_markdown_tag_styles()
        self._schedule_markdown_update()

    def show_icon_menu(self):
        """Show menu to select icon size"""
        menu = self.make_styled_menu()

        # Icon size options
        for size in self.icon_sizes:
            label = f"{'✓ ' if size == self.icon_font_size else '   '}{size}px"
            menu.add_command(label=label, command=lambda s=size: self.set_icon_size(s))

        menu.add_separator()
        menu.add_command(label=self.tr("refresh_display"), command=self.reload_display)
        menu.add_command(label=self.tr("clean_attach"), command=self.cleanup_orphaned_attachments)

        # Show menu at button position
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def set_icon_size(self, size):
        """Set new icon size"""
        self.icon_font_size = size
        self.save_config()
        # Refresh to apply new size
        self.reload_display()

    def show_padding_menu(self):
        """Show menu to select text padding"""
        menu = self.make_styled_menu()

        # Padding size options
        for size in self.padding_sizes:
            label = f"{'✓ ' if size == self.text_padding else '   '}{size}px"
            menu.add_command(label=label, command=lambda s=size: self.set_padding(s))

        # Show menu at button position
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def set_padding(self, size):
        """Set new text area padding"""
        self.text_padding = size
        self.text_area.config(padx=size)
        self.save_config()

    def show_ui_font_menu(self):
        """Show menu to select UI font size"""
        menu = self.make_styled_menu()
        auto_size = self._auto_ui_font_size()
        auto_label = self.tr("ui_font_auto") if hasattr(self, "tr") else "Auto (fit screen)"
        menu.add_command(label=f"   {auto_label} · {auto_size}px",
                         command=lambda s=auto_size: self.set_ui_font_size(s))
        menu.add_separator()
        for size in self.ui_font_sizes:
            label = f"{'✓ ' if size == self.ui_font_size else '   '}{size}px"
            menu.add_command(label=label, command=lambda s=size: self.set_ui_font_size(s))
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def _auto_ui_font_size(self):
        """Pick a comfortable UI font size based on the screen resolution."""
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        except Exception:
            return 13
        # Larger / higher-resolution screens comfortably fit a bigger UI font.
        diag = (sw ** 2 + sh ** 2) ** 0.5
        if diag >= 4000:        # ~3840x2160 (4K) and up
            target = 16
        elif diag >= 2900:      # ~2560x1440
            target = 15
        elif diag >= 2200:      # ~1920x1080
            target = 14
        elif diag >= 1700:      # ~1440x900 / 1366x768
            target = 13
        else:
            target = 12
        # Snap to the nearest available size
        return min(self.ui_font_sizes, key=lambda s: abs(s - target))

    def _ui_size_btn_label(self):
        """Toolbar label for the UI-font button, always showing the actual size."""
        return f"{self.tr('ui_size_btn')} {self.ui_font_size}"

    def set_ui_font_size(self, size):
        """Set new UI font size and refresh all UI elements"""
        self.ui_font_size = size
        # Re-apply theme to update all styles and widgets
        self.apply_theme(self.current_theme)
        # Keep the toolbar button showing the actual current size
        if hasattr(self, "_btn_ui_size"):
            self._btn_ui_size.configure(text=self._ui_size_btn_label())
        self.save_config()

    def ensure_notebooks_dir(self):
        """Create notebooks directory if it doesn't exist"""
        if not os.path.exists(self.notebooks_dir):
            os.makedirs(self.notebooks_dir)
        # Create default notebook if no notebooks exist
        default_path = os.path.join(self.notebooks_dir, "默认")
        if not os.path.exists(default_path):
            os.makedirs(default_path)
            # Migrate old data from root directory to default notebook
            self.migrate_old_data(default_path)

    def migrate_old_data(self, default_path):
        """Migrate old notes.txt and attachments to default notebook"""
        # Migrate notes.txt
        old_notes = "notes.txt"
        if os.path.exists(old_notes):
            try:
                shutil.move(old_notes, os.path.join(default_path, "notes.txt"))
                print("Migrated notes.txt to default notebook")
            except Exception as e:
                print(f"Error migrating notes.txt: {e}")

        # Migrate attachments directory
        old_attachments = "attachments"
        if os.path.exists(old_attachments) and os.path.isdir(old_attachments):
            try:
                new_attachments = os.path.join(default_path, "attachments")
                shutil.move(old_attachments, new_attachments)
                print("Migrated attachments to default notebook")
            except Exception as e:
                print(f"Error migrating attachments: {e}")

    def get_notebook_path(self, notebook_name=None):
        """Get path to notebook directory"""
        if notebook_name is None:
            notebook_name = self.current_notebook
        return os.path.join(self.notebooks_dir, notebook_name)

    def get_note_file_path(self):
        """Get path to current notebook's note file"""
        return os.path.join(self.get_notebook_path(), self.note_file)

    def get_attachments_path(self):
        """Get path to current notebook's attachments directory"""
        return os.path.join(self.get_notebook_path(), self.attachments_dir)

    def get_notebooks_list(self):
        """Get list of all notebooks, respecting shortcuts and custom order"""
        notebooks = []
        if os.path.exists(self.notebooks_dir):
            for name in os.listdir(self.notebooks_dir):
                path = os.path.join(self.notebooks_dir, name)
                if os.path.isdir(path) and not name.startswith('.'):
                    notebooks.append(name)

        # Load saved order and shortcuts (uses cache)
        self.load_notebook_order()

        # Sort: shortcuts first (in their order), then others by most recently
        # modified note (newest first)
        shortcuts_set = set(self.notebook_shortcuts)

        def get_notebook_mtime(name):
            """Last modification time of a notebook's note file (0 if missing)"""
            note_path = os.path.join(self.notebooks_dir, name, self.note_file)
            try:
                return os.path.getmtime(note_path)
            except OSError:
                try:
                    return os.path.getmtime(os.path.join(self.notebooks_dir, name))
                except OSError:
                    return 0

        def sort_key(name):
            is_shortcut = name in shortcuts_set
            if is_shortcut:
                return (0, self.notebook_shortcuts.index(name), 0, name)
            else:
                # Newest modified first: negate mtime so larger times sort earlier
                return (1, -get_notebook_mtime(name), 0, name)

        return sorted(notebooks, key=sort_key)

    def load_notebook_order(self, force=False):
        """Load notebook order and shortcuts from file (cached)"""
        # Use cache if already loaded
        if not force and self.notebook_order is not None and hasattr(self, '_notebook_order_loaded'):
            return

        if os.path.exists(self.notebook_order_file):
            try:
                with open(self.notebook_order_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Support both old format (list) and new format (dict)
                    if isinstance(data, list):
                        self.notebook_order = data
                        self.notebook_shortcuts = []
                    else:
                        self.notebook_order = data.get("order", [])
                        self.notebook_shortcuts = data.get("shortcuts", [])
            except Exception as e:
                print(f"Error loading notebook order: {e}")
                self.notebook_order = []
                self.notebook_shortcuts = []
        else:
            self.notebook_order = []
            self.notebook_shortcuts = []

        self._notebook_order_loaded = True

    def save_notebook_order(self):
        """Save notebook order and shortcuts to file"""
        try:
            data = {
                "order": self.notebook_order,
                "shortcuts": self.notebook_shortcuts
            }
            with open(self.notebook_order_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving notebook order: {e}")

    def add_notebook_shortcut(self, notebook_name):
        """Add notebook to shortcuts (pinned at top)"""
        self.load_notebook_order(force=True)
        if notebook_name not in self.notebook_shortcuts:
            self.notebook_shortcuts.append(notebook_name)
            self.save_notebook_order()
            self.refresh_notebook_listbox(self.notebook_search_var.get())
            self.update_notebook_menu()

    def remove_notebook_shortcut(self, notebook_name):
        """Remove notebook from shortcuts"""
        self.load_notebook_order(force=True)
        if notebook_name in self.notebook_shortcuts:
            self.notebook_shortcuts.remove(notebook_name)
            self.save_notebook_order()
            self.refresh_notebook_listbox(self.notebook_search_var.get())
            self.update_notebook_menu()

    def move_notebook_up(self, notebook_name):
        """Move notebook up in the list"""
        notebooks = self.get_notebooks_list()
        if notebook_name not in notebooks:
            return

        # Update order list to include all current notebooks
        self.notebook_order = notebooks.copy()

        idx = self.notebook_order.index(notebook_name)
        if idx > 0:
            # Swap with previous
            self.notebook_order[idx], self.notebook_order[idx - 1] = \
                self.notebook_order[idx - 1], self.notebook_order[idx]
            self.save_notebook_order()
            self.refresh_notebook_listbox(self.notebook_search_var.get())
            self.update_notebook_menu()

    def move_notebook_down(self, notebook_name):
        """Move notebook down in the list"""
        notebooks = self.get_notebooks_list()
        if notebook_name not in notebooks:
            return

        # Update order list to include all current notebooks
        self.notebook_order = notebooks.copy()

        idx = self.notebook_order.index(notebook_name)
        if idx < len(self.notebook_order) - 1:
            # Swap with next
            self.notebook_order[idx], self.notebook_order[idx + 1] = \
                self.notebook_order[idx + 1], self.notebook_order[idx]
            self.save_notebook_order()
            self.refresh_notebook_listbox(self.notebook_search_var.get())
            self.update_notebook_menu()

    def show_notebook_order_dialog(self):
        """Show dialog to manage notebook order with keyboard support"""
        t = self.current_theme_colors
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr("nb_order_title"))
        dialog.geometry("300x400")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=t["bg"])

        # Instructions
        tk.Label(dialog, text=self.tr("order_hint"),
                 font=(SYSTEM_FONT, self.ui_font_size), bg=t["bg"], fg=t["fg"]).pack(pady=10)

        # List frame
        list_frame = tk.Frame(dialog, bg=t["bg"])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Listbox with scrollbar
        scrollbar = ttk.Scrollbar(list_frame, style="Visible.Vertical.TScrollbar")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        order_listbox = tk.Listbox(list_frame, font=(SYSTEM_FONT, self.ui_font_size),
                                   selectmode=tk.SINGLE, exportselection=False,
                                   bg=t["list_bg"], fg=t["list_fg"],
                                   selectbackground=t["list_select_bg"],
                                   selectforeground=t["list_select_fg"],
                                   highlightthickness=0, relief=tk.FLAT,
                                   activestyle="none")
        order_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        order_listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=order_listbox.yview)

        # Load notebooks
        notebooks = self.get_notebooks_list()
        for name in notebooks:
            order_listbox.insert(tk.END, name)

        # Select first item
        if notebooks:
            order_listbox.selection_set(0)
            order_listbox.focus_set()

        def move_up(event=None):
            selection = order_listbox.curselection()
            if not selection or selection[0] == 0:
                return
            idx = selection[0]
            name = order_listbox.get(idx)
            order_listbox.delete(idx)
            order_listbox.insert(idx - 1, name)
            order_listbox.selection_clear(0, tk.END)
            order_listbox.selection_set(idx - 1)
            order_listbox.see(idx - 1)

        def move_down(event=None):
            selection = order_listbox.curselection()
            if not selection or selection[0] >= order_listbox.size() - 1:
                return
            idx = selection[0]
            name = order_listbox.get(idx)
            order_listbox.delete(idx)
            order_listbox.insert(idx + 1, name)
            order_listbox.selection_clear(0, tk.END)
            order_listbox.selection_set(idx + 1)
            order_listbox.see(idx + 1)

        def save_order():
            # Save the new order
            self.notebook_order = list(order_listbox.get(0, tk.END))
            self.save_notebook_order()
            self.refresh_notebook_listbox(self.notebook_search_var.get())
            self.update_notebook_menu()
            dialog.destroy()

        def cancel():
            dialog.destroy()

        # Bind keyboard shortcuts
        order_listbox.bind("<Up>", lambda e: (move_up(), "break")[1])
        order_listbox.bind("<Down>", lambda e: (move_down(), "break")[1])
        dialog.bind("<Return>", lambda e: save_order())
        dialog.bind("<Escape>", lambda e: cancel())

        # Button frame
        btn_frame = tk.Frame(dialog, bg=t["bg"])
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text=self.tr("up_btn"), command=move_up, width=8,
                   style="Toolbar.TButton").pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text=self.tr("down_btn"), command=move_down, width=8,
                   style="Toolbar.TButton").pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text=self.tr("confirm"), command=save_order, width=8,
                   style="Toolbar.TButton").pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text=self.tr("cancel"), command=cancel, width=8,
                   style="Toolbar.TButton").pack(side=tk.RIGHT, padx=5)

        # Center dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

    def refresh_notebook_listbox(self, search_text=""):
        """Refresh the notebook list with optional search filter"""
        tree = self.notebook_listbox
        tree.delete(*tree.get_children())
        notebooks = self.get_notebooks_list()

        # Filter by search text
        if search_text:
            search_lower = search_text.lower()
            notebooks = [n for n in notebooks if search_lower in n.lower()]

        # Add notebooks with shortcut indicator (iid = actual notebook name)
        for name in notebooks:
            display_name = f"★ {name}" if name in self.notebook_shortcuts else name
            tree.insert("", tk.END, iid=name, text=display_name)

        # Highlight current notebook
        self.highlight_current_notebook()

    def highlight_current_notebook(self):
        """Highlight the current notebook in the list"""
        tree = self.notebook_listbox
        if self.current_notebook and self.current_notebook in tree.get_children():
            tree.selection_set(self.current_notebook)
            tree.focus(self.current_notebook)
            tree.see(self.current_notebook)

    def get_actual_notebook_name(self, display_name):
        """Get actual notebook name from display name (remove ★ prefix if present)"""
        if display_name.startswith("★ "):
            return display_name[2:]
        return display_name

    def on_notebook_search_changed(self, *args):
        """Handle search text change"""
        search_text = self.notebook_search_var.get()
        self.refresh_notebook_listbox(search_text)

    def on_notebook_listbox_select(self, event):
        """Handle selection change in the notebook list"""
        if getattr(self, '_drag_active', False):
            return
        selection = self.notebook_listbox.selection()
        if selection:
            actual_name = selection[0]  # iid is the actual notebook name
            if actual_name != self.current_notebook:
                self.switch_notebook(actual_name)

    def on_notebook_listbox_double_click(self, event):
        """Handle double click on notebook list - show context menu"""
        selection = self.notebook_listbox.selection()
        if selection:
            self.show_notebook_context_menu(event, selection[0])

    def on_notebook_listbox_right_click(self, event):
        """Handle right click on notebook list - show context menu"""
        # Select the item under cursor
        iid = self.notebook_listbox.identify_row(event.y)
        if iid:
            self.notebook_listbox.selection_set(iid)
            self.show_notebook_context_menu(event, iid)

    def _on_listbox_drag_start(self, event):
        """Record the item where the drag starts."""
        self._drag_start_iid = self.notebook_listbox.identify_row(event.y)
        self._drag_active = False
        self._drag_out_of_bounds = False

    def _on_listbox_drag_motion(self, event):
        """Move the dragged item as the mouse moves."""
        if not getattr(self, '_drag_start_iid', None):
            return
        tree = self.notebook_listbox
        w, h = tree.winfo_width(), tree.winfo_height()
        # Detect drag outside list bounds
        if event.x < -20 or event.x > w + 20 or event.y < -20 or event.y > h + 20:
            self._drag_out_of_bounds = True
            tree.config(cursor="plus")
            return
        else:
            self._drag_out_of_bounds = False
            tree.config(cursor="")

        target = tree.identify_row(event.y)
        if not target or target == self._drag_start_iid:
            if not self._drag_active and target and target != self._drag_start_iid:
                self._drag_active = True
            return
        self._drag_active = True
        # Move the dragged item to the target position
        tree.move(self._drag_start_iid, "", tree.index(target))
        tree.selection_set(self._drag_start_iid)

    def _on_listbox_drag_end(self, event):
        """Finalize the drag: persist reorder or open floating viewer."""
        self.notebook_listbox.config(cursor="")
        if getattr(self, '_drag_out_of_bounds', False):
            # Dragged outside list -> open floating viewer
            if getattr(self, '_drag_start_iid', None):
                self._open_notebook_viewer(self._drag_start_iid)
            self._drag_start_iid = None
            self._drag_active = False
            self._drag_out_of_bounds = False
            self.refresh_notebook_listbox(self.notebook_search_var.get())
            return

        if self._drag_active:
            # Rebuild notebook_order from the current list order (iids = names)
            self.notebook_order = list(self.notebook_listbox.get_children())
            self.save_notebook_order()
            self.update_notebook_menu()
            self.highlight_current_notebook()
        self._drag_start_iid = None
        self._drag_active = False

    def _viewer_ctx(self, viewer):
        """Context manager that swaps NoteApp state to operate on a viewer window."""
        class _Ctx:
            def __init__(ctx):
                ctx.app = self
            def __enter__(ctx):
                ctx.saved = {
                    'text_area': self.text_area,
                    'images': self.images,
                    'image_widths': self.image_widths,
                    'filename_map': self.filename_map,
                    'url_tags': self.url_tags,
                    'url_preview_tags': self._url_preview_tags,
                    'current_notebook': self.current_notebook,
                    'md_marker_ranges': self._md_marker_ranges,
                    'fast_load_mode': getattr(self, '_fast_load_mode', False),
                    'deferred_images': getattr(self, '_deferred_images', []),
                    'md_active_line': getattr(self, '_md_active_line', None),
                    'video_thumb_cache': self._video_thumb_cache,
                }
                self.text_area = viewer._nb_text
                self.images = viewer._nb_images
                self.image_widths = viewer._nb_image_widths
                self.url_tags = viewer._nb_url_tags
                self._url_preview_tags = viewer._nb_url_preview_tags
                self.current_notebook = viewer._nb_name
                self._md_marker_ranges = viewer._nb_md_marker_ranges
                self._fast_load_mode = False
                self._deferred_images = []
                self._md_active_line = viewer._nb_md_active_line
                self._video_thumb_cache = viewer._nb_video_thumb_cache
                self.filename_map = viewer._nb_filename_map
                return ctx
            def __exit__(ctx, *args):
                # Save viewer state back
                viewer._nb_images = self.images
                viewer._nb_image_widths = self.image_widths
                viewer._nb_url_tags = self.url_tags
                viewer._nb_url_preview_tags = self._url_preview_tags
                viewer._nb_md_marker_ranges = self._md_marker_ranges
                viewer._nb_md_active_line = self._md_active_line
                viewer._nb_video_thumb_cache = self._video_thumb_cache
                viewer._nb_filename_map = self.filename_map
                # Restore main state
                s = ctx.saved
                self.text_area = s['text_area']
                self.images = s['images']
                self.image_widths = s['image_widths']
                self.filename_map = s['filename_map']
                self.url_tags = s['url_tags']
                self._url_preview_tags = s['url_preview_tags']
                self.current_notebook = s['current_notebook']
                self._md_marker_ranges = s['md_marker_ranges']
                self._fast_load_mode = s['fast_load_mode']
                self._deferred_images = s['deferred_images']
                self._md_active_line = s['md_active_line']
                self._video_thumb_cache = s['video_thumb_cache']
        return _Ctx()

    def _open_notebook_viewer(self, notebook_name):
        """Open an editable floating window for the given notebook."""
        # Prevent duplicate viewers
        for v in self._notebook_viewers:
            try:
                if v.winfo_exists() and v._nb_name == notebook_name:
                    v.lift()
                    v.focus_force()
                    return
            except:
                pass
        self._notebook_viewers = [v for v in self._notebook_viewers
                                  if v.winfo_exists()]

        t = self.current_theme_colors
        viewer = tk.Toplevel(self.root)
        viewer.title(f"{self.tr('nb_viewer_title')} - {notebook_name}")
        viewer.geometry("600x700")
        viewer.configure(bg=t["bg"])
        viewer._nb_name = notebook_name
        viewer._nb_save_timer = None
        viewer._nb_md_timer = None
        if self.always_on_top.get():
            viewer.wm_attributes("-topmost", 1)

        # Text widget with scrollbar
        text_frame = tk.Frame(viewer, bg=t["bg"])
        text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        viewer_text = tk.Text(
            text_frame, wrap=tk.WORD,
            font=(SYSTEM_FONT, self.current_font_size),
            padx=getattr(self, 'text_padding', 10),
            bg=t["text_bg"], fg=t["text_fg"],
            insertbackground=t["text_insert"],
            selectbackground=t["text_select_bg"],
            relief=tk.FLAT, highlightthickness=0,
            undo=True)
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL,
                                  command=viewer_text.yview,
                                  style="Visible.Vertical.TScrollbar")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        viewer_text.config(yscrollcommand=scrollbar.set)
        viewer_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Initialize viewer-specific state
        viewer._nb_text = viewer_text
        viewer._nb_images = {}
        viewer._nb_image_widths = {}
        viewer._nb_url_tags = set()
        viewer._nb_url_preview_tags = set()
        viewer._nb_md_marker_ranges = {}
        viewer._nb_md_active_line = None
        viewer._nb_video_thumb_cache = {}
        viewer._nb_filename_map = {}

        # Load content using context swap
        with self._viewer_ctx(viewer):
            try:
                self.load_filename_map()
                viewer._nb_filename_map = self.filename_map
                self.setup_markdown_tags()
                self._update_text_tags()
                note_path = os.path.join(self.notebooks_dir, notebook_name, self.note_file)
                if os.path.exists(note_path):
                    with open(note_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    self.load_content_with_images(content)
            except Exception as e:
                print(f"Error loading viewer for {notebook_name}: {e}")

        # Auto-save on edit (debounced)
        def on_viewer_modified(event=None):
            if viewer._nb_save_timer is not None:
                self.root.after_cancel(viewer._nb_save_timer)
            viewer._nb_save_timer = self.root.after(2000, lambda: self._viewer_save(viewer))
            if viewer._nb_md_timer is not None:
                self.root.after_cancel(viewer._nb_md_timer)
            viewer._nb_md_timer = self.root.after(300, lambda: self._viewer_update_md(viewer))

        viewer_text.bind("<KeyRelease>", on_viewer_modified, add="+")

        # Cmd+V / Ctrl+V — paste images, files (incl. videos), and internal links
        def on_viewer_paste(event=None):
            if not PIL_AVAILABLE:
                return None
            self.is_pasting = True
            try:
                with self._viewer_ctx(viewer):
                    try:
                        result = self._do_paste()
                    except Exception as e:
                        print(f"Error in viewer paste: {e}")
                        result = None
                    # Cancel main-editor-bound auto-save timer set by _do_paste
                    if self.auto_save_timer_id is not None:
                        try:
                            self.root.after_cancel(self.auto_save_timer_id)
                        except Exception:
                            pass
                        self.auto_save_timer_id = None
                # After context exits, persist viewer state and re-render markdown
                self._viewer_save(viewer)
                self._viewer_update_md(viewer)
                # Sync main editor if it's showing the same notebook
                if viewer._nb_name == self.current_notebook:
                    self._reload_current_from_disk()
                return "break" if result == "break" else None
            finally:
                self.is_pasting = False

        viewer_text.bind("<Command-v>", on_viewer_paste)
        viewer_text.bind("<Control-v>", on_viewer_paste)

        # Cmd+C / Ctrl+C — copy with file/image awareness
        def on_viewer_copy(event=None):
            try:
                with self._viewer_ctx(viewer):
                    return self.handle_copy(event)
            except Exception as e:
                print(f"Error in viewer copy: {e}")
                return None

        viewer_text.bind("<Command-c>", on_viewer_copy)
        viewer_text.bind("<Control-c>", on_viewer_copy)

        # Cmd+X / Ctrl+X — cut with file/image/rich awareness
        def on_viewer_cut(event=None):
            try:
                with self._viewer_ctx(viewer):
                    result = self.on_before_cut(event)
                # Sync viewer state and re-render markdown after the cut
                self._viewer_save(viewer)
                self._viewer_update_md(viewer)
                if viewer._nb_name == self.current_notebook:
                    self._reload_current_from_disk()
                return result
            except Exception as e:
                print(f"Error in viewer cut: {e}")
                return None

        viewer_text.bind("<Command-x>", on_viewer_cut)
        viewer_text.bind("<Control-x>", on_viewer_cut)

        # Cmd+S / Ctrl+S to save and sync immediately
        def on_viewer_save(event=None):
            self._viewer_save(viewer)
            if viewer._nb_name == self.current_notebook:
                self._reload_current_from_disk()

        viewer.bind("<Command-s>", on_viewer_save)
        viewer.bind("<Control-s>", on_viewer_save)

        # Close handler: save, sync, then destroy
        def on_viewer_close():
            self._viewer_save(viewer)
            if viewer._nb_save_timer is not None:
                self.root.after_cancel(viewer._nb_save_timer)
            if viewer._nb_md_timer is not None:
                self.root.after_cancel(viewer._nb_md_timer)
            self._notebook_viewers = [v for v in self._notebook_viewers
                                      if v != viewer]
            viewer.destroy()
            # Sync main editor if it's showing the same notebook
            if viewer._nb_name == self.current_notebook:
                self._reload_current_from_disk()

        viewer.protocol("WM_DELETE_WINDOW", on_viewer_close)
        self._notebook_viewers.append(viewer)

    def _viewer_get_content(self, viewer):
        """Serialize the viewer's text content with markers (images, highlights, etc.)."""
        vt = viewer._nb_text
        result = []
        dump_data = vt.dump("1.0", tk.END, text=True, image=True)

        def _idx(s):
            line, col = s.split(".")
            return (int(line), int(col))

        # Build skip ranges for url_preview_, icon_, imgname_ tags
        skip_ranges = []
        file_markers = {}
        for tag in vt.tag_names():
            if tag.startswith("icon_"):
                internal_filename = tag[5:]
                ranges = vt.tag_ranges(tag)
                if ranges:
                    icon_start = str(ranges[0])
                    file_tag = f"file_{internal_filename}"
                    file_ranges = vt.tag_ranges(file_tag)
                    if file_ranges:
                        file_end = str(file_ranges[1])
                        s, e = _idx(icon_start), _idx(file_end)
                        skip_ranges.append((s, e))
                        file_markers[s] = f"[FILE:{internal_filename}]"
            elif tag.startswith("imgname_"):
                internal_filename = tag[8:]
                ranges = vt.tag_ranges(tag)
                if ranges:
                    name_start = str(ranges[0])
                    name_end = str(ranges[1])
                    prev_idx = vt.index(f"{name_start}-1c")
                    if vt.get(prev_idx) == "\n":
                        name_start = prev_idx
                    skip_ranges.append((_idx(name_start), _idx(name_end)))
            elif tag.startswith("url_preview_"):
                ranges = vt.tag_ranges(tag)
                for ri in range(0, len(ranges), 2):
                    skip_ranges.append((_idx(str(ranges[ri])), _idx(str(ranges[ri + 1]))))
        skip_ranges.sort()

        # Strikethrough boundaries
        strike_starts = set()
        strike_ends = set()
        strike_raw = vt.tag_ranges("strikethrough")
        for si in range(0, len(strike_raw), 2):
            strike_starts.add(_idx(str(strike_raw[si])))
            strike_ends.add(_idx(str(strike_raw[si + 1])))

        # Highlight boundaries
        hl_starts = {}
        hl_ends = {}
        for color in self.HIGHLIGHT_NAMES:
            raw = vt.tag_ranges(f"highlight_{color}")
            for hi in range(0, len(raw), 2):
                hl_starts[_idx(str(raw[hi]))] = color
                hl_ends[_idx(str(raw[hi + 1]))] = color

        def is_in_skip_range(t):
            for s, e in skip_ranges:
                if s <= t < e:
                    return True
                if s > t:
                    break
            return False

        emitted_starts = set()
        emitted_ends = set()
        i = 0
        while i < len(dump_data):
            key, value, index = dump_data[i]
            t = _idx(index)
            marker = file_markers.get(t)
            if marker:
                result.append(marker)
                end = None
                for s, e in skip_ranges:
                    if s == t:
                        end = e
                        break
                while i < len(dump_data):
                    _, _, idx2 = dump_data[i]
                    if end and _idx(idx2) >= end:
                        break
                    i += 1
                continue
            if is_in_skip_range(t):
                i += 1
                continue
            if t in hl_ends and t not in emitted_ends:
                result.append('[/HL]')
                emitted_ends.add(t)
            if t in hl_starts and t not in emitted_starts:
                result.append(f'[HL:{hl_starts[t]}]')
                emitted_starts.add(t)
            if t in strike_ends and t not in emitted_ends:
                result.append('[/STRIKE]')
                emitted_ends.add(t)
            if t in strike_starts and t not in emitted_starts:
                result.append('[STRIKE]')
                emitted_starts.add(t)
            if key == "text":
                result.append(value)
            elif key == "image":
                width = viewer._nb_image_widths.get(value, "")
                if width:
                    result.append(f"[IMAGE:{value}:{width}]")
                else:
                    result.append(f"[IMAGE:{value}]")
            i += 1

        # Close any unclosed markers
        if strike_starts - emitted_ends:
            result.append('[/STRIKE]')
        open_hls = set(hl_starts.keys()) - emitted_ends
        if open_hls:
            result.append('[/HL]')

        text = ''.join(result)
        if text.endswith('\n'):
            text = text[:-1]
        return text

    def _viewer_save(self, viewer):
        """Save the floating viewer's content to disk."""
        try:
            if not viewer.winfo_exists():
                return
        except:
            return
        try:
            content = self._viewer_get_content(viewer)
            note_path = os.path.join(self.notebooks_dir, viewer._nb_name, self.note_file)
            with open(note_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            print(f"Error saving viewer {viewer._nb_name}: {e}")
            import traceback
            traceback.print_exc()

    def _viewer_update_md(self, viewer):
        """Re-apply markdown formatting in the floating viewer."""
        try:
            if not viewer.winfo_exists():
                return
        except:
            return
        # Apply basic markdown tags directly on the viewer text widget
        vt = viewer._nb_text
        t = self.current_theme_colors
        sz = self.current_font_size
        fg = t["fg"]
        dim = t["fg_dim"]
        accent = t["accent"]

        # Remove old md_ tags
        for tag in vt.tag_names():
            if tag.startswith("md_"):
                vt.tag_remove(tag, "1.0", tk.END)
        vt.tag_configure("md_elide", elide=True)

        content = vt.get("1.0", tk.END)
        viewer._nb_md_marker_ranges = {}

        for i, line in enumerate(content.split('\n')):
            line_num = i + 1
            line_start = f"{line_num}.0"
            # Headings
            m = re.match(r'^(#{1,3})\s+(.+)', line)
            if m:
                level = len(m.group(1))
                marker_end = len(m.group(1)) + 1
                hsz = int(sz * {1: 1.6, 2: 1.35, 3: 1.15}[level])
                tag_marker = f"md_h{level}_marker"
                tag_text = f"md_h{level}_text"
                vt.tag_configure(tag_marker, foreground=dim, font=(SYSTEM_FONT, hsz, "bold"))
                vt.tag_configure(tag_text, foreground=fg, font=(SYSTEM_FONT, hsz, "bold"))
                vt.tag_add(tag_marker, f"{line_num}.0", f"{line_num}.{marker_end}")
                vt.tag_add(tag_text, f"{line_num}.{marker_end}", f"{line_num}.end")
                # Elide the heading markers
                s = f"{line_num}.0"
                e = f"{line_num}.{marker_end}"
                vt.tag_add("md_elide", s, e)
                viewer._nb_md_marker_ranges.setdefault(line_num, []).append((s, e))

        vt.tag_raise("md_elide")

    def _reload_current_from_disk(self):
        """Reload the main editor from disk for the current notebook."""
        note_path = self.get_note_file_path()
        if os.path.exists(note_path):
            try:
                with open(note_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.text_area.delete("1.0", tk.END)
                self.load_content_with_images(content)
                self.text_area.edit_reset()
                self.content_modified = False
            except Exception as e:
                print(f"Error reloading from disk: {e}")

    def _sync_from_viewer(self, viewer):
        """Reload the main editor from an open viewer (save viewer to disk, then reload)."""
        try:
            if not viewer.winfo_exists():
                return
        except:
            return
        # Save viewer content to disk
        self._viewer_save(viewer)
        # Reload main editor from disk
        note_path = self.get_note_file_path()
        if os.path.exists(note_path):
            try:
                with open(note_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.text_area.delete("1.0", tk.END)
                self.load_content_with_images(content)
                self.text_area.edit_reset()
            except Exception as e:
                print(f"Error syncing from viewer: {e}")

    def show_notebook_context_menu(self, event, notebook_name):
        """Show context menu for notebook operations"""
        menu = self.make_styled_menu()

        # Shortcut options
        if notebook_name in self.notebook_shortcuts:
            menu.add_command(label=self.tr("unpin"), command=lambda: self.remove_notebook_shortcut(notebook_name))
        else:
            menu.add_command(label=self.tr("pin"), command=lambda: self.add_notebook_shortcut(notebook_name))

        menu.add_separator()
        menu.add_command(label=self.tr("move_up"), command=lambda: self.move_notebook_up(notebook_name))
        menu.add_command(label=self.tr("move_down"), command=lambda: self.move_notebook_down(notebook_name))
        menu.add_separator()
        menu.add_command(label=self.tr("open_viewer"), command=lambda: self._open_notebook_viewer(notebook_name))
        menu.add_separator()
        menu.add_command(label=self.tr("export_nb"),
                         command=lambda: self.export_notebook(notebook_name))
        menu.add_command(label=self.tr("import_nb"), command=self.import_notebook)
        menu.add_separator()
        menu.add_command(label=self.tr("rename_dots"), command=lambda: self.rename_specific_notebook(notebook_name))
        if notebook_name != "默认":
            menu.add_command(label=self.tr("delete"), command=lambda: self.delete_specific_notebook(notebook_name))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def rename_specific_notebook(self, notebook_name):
        """Rename a specific notebook"""
        if notebook_name == "默认":
            import tkinter.messagebox as messagebox
            messagebox.showwarning(self.tr("warning"), self.tr("no_rename_def"))
            return

        # Switch to this notebook first if not current
        if notebook_name != self.current_notebook:
            self.switch_notebook(notebook_name)
        self.rename_notebook()

    def delete_specific_notebook(self, notebook_name):
        """Delete a specific notebook"""
        import tkinter.messagebox as messagebox

        if notebook_name == "默认":
            messagebox.showwarning(self.tr("warning"), self.tr("no_delete_def"))
            return

        if messagebox.askyesno(self.tr("confirm_del"), self.tr("confirm_del_msg").format(notebook_name)):
            notebook_path = os.path.join(self.notebooks_dir, notebook_name)
            # If deleting current notebook, switch to default first
            if notebook_name == self.current_notebook:
                self.current_notebook = "默认"
            # Delete the notebook directory
            shutil.rmtree(notebook_path)
            # Update UI
            self.update_notebook_menu()
            self.refresh_notebook_listbox(self.notebook_search_var.get())
            if self.current_notebook == "默认":
                self.switch_notebook("默认")

    def update_notebook_menu(self):
        """Update the notebook combobox with current notebooks"""
        notebooks = self.get_notebooks_list()
        if hasattr(self, 'notebook_combo'):
            self.notebook_combo["values"] = notebooks
            self.notebook_var.set(self.current_notebook)

    def _on_combo_selected(self, event=None):
        """Handle notebook selection from combobox"""
        selected = self.notebook_var.get()
        if selected and selected != self.current_notebook:
            self.switch_notebook(selected)
        self.notebook_var.set(self.current_notebook)

    def on_notebook_selected(self, notebook_name):
        """Handle notebook selection from dropdown/menu"""
        if notebook_name != self.current_notebook:
            self.switch_notebook(notebook_name)
        self.notebook_var.set(self.current_notebook)

    def show_notebook_menu(self):
        """Show menu to select or create notebook"""
        menu = self.make_styled_menu()

        # List all notebooks
        notebooks = self.get_notebooks_list()
        for name in notebooks:
            label = f"{'✓ ' if name == self.current_notebook else '   '}{name}"
            menu.add_command(label=label, command=lambda n=name: self.switch_notebook(n))

        menu.add_separator()
        menu.add_command(label=self.tr("new_nb_dots"), command=self.create_notebook)
        menu.add_command(label=self.tr("rename_cur_nb"), command=self.rename_notebook)
        menu.add_command(label=self.tr("delete_cur_nb"), command=self.delete_notebook)
        menu.add_separator()
        menu.add_command(label=self.tr("sort_manage"), command=self.show_notebook_order_dialog)
        menu.add_separator()
        menu.add_command(label=self.tr("export_nb"), command=self.export_notebook)
        menu.add_command(label=self.tr("import_nb"), command=self.import_notebook)

        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def switch_notebook(self, notebook_name):
        """Switch to a different notebook"""
        if notebook_name == self.current_notebook:
            return

        # Save current notes before switching (quick mode for faster switch)
        self.save_notes(quick=True)

        # If the target notebook has an open viewer, save it first so we load latest
        for viewer in self._notebook_viewers:
            try:
                if viewer.winfo_exists() and viewer._nb_name == notebook_name:
                    self._viewer_save(viewer)
                    break
            except:
                pass

        # Remember previous notebook for quick switch
        self.previous_notebook = self.current_notebook

        # Switch notebook
        self.current_notebook = notebook_name

        # Ensure attachments directory exists for new notebook
        attachments_path = self.get_attachments_path()
        if not os.path.exists(attachments_path):
            os.makedirs(attachments_path)

        # Update window title and UI first (instant feedback)
        self.root.title(f"Quick Note Board - {notebook_name}")
        self.notebook_var.set(notebook_name)
        self.highlight_current_notebook()

        # Cancel any pending auto-save
        if self.auto_save_timer_id is not None:
            self.root.after_cancel(self.auto_save_timer_id)
            self.auto_save_timer_id = None

        # Close search bar if open
        self._close_search_bar()

        # Clear state and delete stale tag names to keep tag_names() fast
        ta = self.text_area
        for tag in list(ta.tag_names()):
            if tag.startswith(("url_", "file_", "icon_", "imgtag_", "imgname_", "url_preview_", "md_", "nb_link_")):
                ta.tag_delete(tag)
        self.images.clear()
        self.image_widths.clear()
        self.url_tags.clear()
        self._url_preview_tags.clear()
        self._video_thumb_cache.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()

        # Reload filename map for new notebook
        self.load_filename_map()

        # Load notes from new notebook
        note_path = self.get_note_file_path()
        loaded_content = ""

        # Cancel any pending deferred image loading from previous switch
        if hasattr(self, '_deferred_load_timer') and self._deferred_load_timer is not None:
            self.root.after_cancel(self._deferred_load_timer)
            self._deferred_load_timer = None
        self._deferred_images = []

        # Suppress widget redraws during bulk load by temporarily hiding
        self.text_area.pack_forget()
        self._fast_load_mode = True
        try:
            # Clear and load content with saved image sizes
            # Images are inserted as tiny placeholders; real loading is deferred
            self.text_area.delete("1.0", tk.END)
            if os.path.exists(note_path):
                try:
                    with open(note_path, "r", encoding="utf-8") as f:
                        loaded_content = f.read()
                        self.load_content_with_images(loaded_content, use_thumbnails=False)
                except Exception as e:
                    print(f"Error loading notes: {e}")
        finally:
            self._fast_load_mode = False
            # Re-show text area (before scrollbar so it fills correctly)
            self.text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Reset state after loading
        self.last_saved_content = loaded_content
        self.content_modified = False
        self.text_area.edit_reset()  # Clear Tk native undo stack (loading is not undoable)

        # Set focus to text area for editing
        self.text_area.focus_set()

        # Start progressive image loading — offscreen images first (no layout shift
        # visible to user), then visible images pop in at the end
        if self._deferred_images:
            self.root.update_idletasks()
            try:
                wh = self.text_area.winfo_height()
                last_vis = int(self.text_area.index(f"@0,{wh}").split('.')[0])
            except Exception:
                last_vis = 50
            visible, offscreen = [], []
            for item in self._deferred_images:
                fp, fn, w = item
                try:
                    img_name = f"vidthumb_{fn}" if fp == '__video__' else f"img_{fn}"
                    line = int(self.text_area.index(img_name).split('.')[0])
                    (visible if line <= last_vis else offscreen).append(item)
                except Exception:
                    offscreen.append(item)
            self._deferred_images = offscreen + visible
            self._deferred_load_timer = self.root.after(10, self._load_deferred_images)

        # Defer config save to avoid blocking
        if not hasattr(self, '_config_save_scheduled') or not self._config_save_scheduled:
            self._config_save_scheduled = True
            self.root.after(1000, self._deferred_save_config)

    def _deferred_save_config(self):
        """Save config after a delay to avoid blocking UI"""
        self._config_save_scheduled = False
        self.save_config()

    def _load_deferred_images(self):
        """Progressively load deferred images/videos one at a time, keeping UI responsive."""
        self._deferred_load_timer = None
        if not self._deferred_images:
            return

        entry = self._deferred_images.pop(0)
        filepath, filename, width = entry

        try:
            # --- Video thumbnail ---
            if filepath == '__video__':
                internal_filename = filename
                vidthumb_id = f"vidthumb_{internal_filename}"
                try:
                    self.text_area.index(vidthumb_id)
                except tk.TclError:
                    self._deferred_images.clear()
                    return

                thumb = self._get_video_thumbnail(internal_filename)
                if thumb is not None:
                    target_width = min(self.max_image_width, 400)
                    target_width = max(50, min(800, target_width))
                    if thumb.width != target_width:
                        ratio = target_width / thumb.width
                        new_height = int(thumb.height * ratio)
                        thumb = thumb.resize((target_width, new_height), Image.Resampling.BOX)
                    photo = ImageTk.PhotoImage(thumb)
                    self.images[vidthumb_id] = photo
                    self.text_area.image_configure(vidthumb_id, image=photo)

                    # Bind click handlers on thumbnail
                    icon_tag = f"icon_{internal_filename}"
                    self.text_area.tag_bind(icon_tag, "<Button-1>", lambda e: self.open_file(internal_filename))
                    self.text_area.tag_bind(icon_tag, "<Button-2>", lambda e: self.show_file_menu(e, internal_filename))
                    self.text_area.tag_bind(icon_tag, "<Button-3>", lambda e: self.show_file_menu(e, internal_filename))
                    self.text_area.tag_bind(icon_tag, "<Enter>", lambda e: self.text_area.config(cursor="hand2"))
                    self.text_area.tag_bind(icon_tag, "<Leave>", lambda e: self.text_area.config(cursor=""))

                    tag_name = f"file_{internal_filename}"
                    self.text_area.tag_bind(tag_name, "<Button-1>", lambda e: self.select_file(internal_filename))
                    self.text_area.tag_bind(tag_name, "<Double-Button-1>", lambda e: self.open_file(internal_filename))
                    self.text_area.tag_bind(tag_name, "<Button-2>", lambda e: self.show_file_menu(e, internal_filename))
                    self.text_area.tag_bind(tag_name, "<Button-3>", lambda e: self.show_file_menu(e, internal_filename))
                    self.text_area.tag_bind(tag_name, "<Enter>", lambda e: self.text_area.config(cursor="hand2"))
                    self.text_area.tag_bind(tag_name, "<Leave>", lambda e: self.text_area.config(cursor=""))

            # --- Regular image ---
            else:
                image_id = f"img_{filename}"
                try:
                    self.text_area.index(image_id)
                except tk.TclError:
                    self._deferred_images.clear()
                    return

                # Determine target width
                target_width = width if width is not None else self.image_widths.get(filename, self.max_image_width)
                target_width = max(50, min(800, target_width))

                # Try loading from thumbnail cache first (~50KB vs 7.6MB original)
                attachments_path = self.get_attachments_path()
                base = os.path.splitext(filename)[0]
                thumb_name = f"_thumb_{base}_{target_width}.jpg"
                thumb_path = os.path.join(attachments_path, thumb_name)

                image = None
                if os.path.exists(thumb_path) and os.path.exists(filepath):
                    if os.path.getmtime(thumb_path) >= os.path.getmtime(filepath):
                        try:
                            image = Image.open(thumb_path)
                            image.load()
                        except Exception:
                            image = None

                if image is None:
                    # Load from original with fast decode
                    image = Image.open(filepath)
                    if image.format == 'JPEG' and image.width > target_width * 3:
                        draft_scale = 1
                        while draft_scale * 2 <= image.width // (target_width * 2) and draft_scale < 8:
                            draft_scale *= 2
                        if draft_scale > 1:
                            image.draft('RGB', (image.width // draft_scale, image.height // draft_scale))
                    elif hasattr(image, 'reduce') and image.width > target_width * 4:
                        try:
                            image = image.reduce(max(2, image.width // (target_width * 2)))
                        except Exception:
                            pass

                    if image.width != target_width:
                        ratio = target_width / image.width
                        new_height = int(image.height * ratio)
                        image = image.resize((target_width, new_height), Image.Resampling.BOX)

                    # Save thumbnail cache for next time
                    try:
                        save_img = image.convert('RGB') if image.mode in ('RGBA', 'P', 'LA') else image
                        save_img.save(thumb_path, 'JPEG', quality=85)
                    except Exception:
                        pass

                self.image_widths[filename] = target_width
                photo = ImageTk.PhotoImage(image)
                self.images[image_id] = photo
                self.text_area.image_configure(image_id, image=photo)

                # Set up tag and event bindings
                img_index = self.text_area.index(image_id)
                tag_name = f"imgtag_{filename}"
                self.text_area.tag_add(tag_name, img_index)
                self.text_area.tag_bind(tag_name, "<Motion>", lambda e, fn=filename: self.on_image_motion(e, fn))
                self.text_area.tag_bind(tag_name, "<ButtonPress-1>", lambda e, fn=filename: self.on_image_press(e, fn))
                self.text_area.tag_bind(tag_name, "<B1-Motion>", lambda e, fn=filename: self.on_image_drag(e, fn))
                self.text_area.tag_bind(tag_name, "<ButtonRelease-1>", lambda e, fn=filename: self.on_image_release(e, fn))
                self.text_area.tag_bind(tag_name, "<Double-Button-1>", lambda e, fn=filename: self.open_image_viewer(e, fn))
                self.text_area.tag_bind(tag_name, "<Button-2>", lambda e: self.show_image_menu(e, filename))
                self.text_area.tag_bind(tag_name, "<Button-3>", lambda e: self.show_image_menu(e, filename))

        except Exception as e:
            print(f"Error loading deferred image/video: {e}")

        # Schedule next load
        if self._deferred_images:
            self._deferred_load_timer = self.root.after(10, self._load_deferred_images)

    def quick_switch_notebook(self, event=None):
        """Quick switch between current and previous notebook (Ctrl+Tab)"""
        if self.previous_notebook and self.previous_notebook != self.current_notebook:
            # Quick check if notebook exists without loading full list
            notebook_path = os.path.join(self.notebooks_dir, self.previous_notebook)
            if os.path.isdir(notebook_path):
                self.switch_notebook(self.previous_notebook)
        # Ensure focus returns to text area
        self.text_area.focus_set()
        return "break"  # Prevent default Tab behavior

    def create_notebook(self):
        """Create a new notebook"""
        t = self.current_theme_colors
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr("new_nb_title"))
        dialog.geometry("300x120")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=t["bg"])

        tk.Label(dialog, text=self.tr("nb_name_label"), bg=t["bg"], fg=t["fg"],
                 font=(SYSTEM_FONT, self.ui_font_size)).pack(pady=(10, 5))
        entry = ttk.Entry(dialog, width=30, style="Sidebar.TEntry")
        entry.pack(pady=5, padx=20)
        entry.focus_set()

        def do_create():
            name = entry.get().strip()
            if name and name not in self.get_notebooks_list():
                notebook_path = os.path.join(self.notebooks_dir, name)
                os.makedirs(notebook_path)
                os.makedirs(os.path.join(notebook_path, self.attachments_dir))
                dialog.destroy()
                self.update_notebook_menu()
                self.refresh_notebook_listbox(self.notebook_search_var.get())
                self.switch_notebook(name)
            elif name in self.get_notebooks_list():
                import tkinter.messagebox as messagebox
                messagebox.showwarning(self.tr("warning"), self.tr("nb_exists"), parent=dialog)

        entry.bind("<Return>", lambda e: do_create())
        ttk.Button(dialog, text=self.tr("create"), command=do_create,
                   style="Toolbar.TButton").pack(pady=10)

    def rename_notebook(self):
        """Rename current notebook"""
        if self.current_notebook == "默认":
            import tkinter.messagebox as messagebox
            messagebox.showwarning(self.tr("warning"), self.tr("no_rename_def"))
            return

        t = self.current_theme_colors
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr("rename_nb_title"))
        dialog.geometry("300x120")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=t["bg"])

        tk.Label(dialog, text=self.tr("new_name_label"), bg=t["bg"], fg=t["fg"],
                 font=(SYSTEM_FONT, self.ui_font_size)).pack(pady=(10, 5))
        entry = ttk.Entry(dialog, width=30, style="Sidebar.TEntry")
        entry.insert(0, self.current_notebook)
        entry.pack(pady=5, padx=20)
        entry.select_range(0, tk.END)
        entry.focus_set()

        def do_rename():
            new_name = entry.get().strip()
            if new_name and new_name != self.current_notebook:
                if new_name in self.get_notebooks_list():
                    import tkinter.messagebox as messagebox
                    messagebox.showwarning(self.tr("warning"), self.tr("nb_exists"), parent=dialog)
                    return
                old_path = self.get_notebook_path()
                new_path = os.path.join(self.notebooks_dir, new_name)
                os.rename(old_path, new_path)
                self.current_notebook = new_name
                self.root.title(f"Quick Note Board - {new_name}")
                self.notebook_var.set(new_name)
                self.update_notebook_menu()
                self.refresh_notebook_listbox(self.notebook_search_var.get())
                self.save_config()
                dialog.destroy()

        entry.bind("<Return>", lambda e: do_rename())
        ttk.Button(dialog, text=self.tr("rename"), command=do_rename,
                   style="Toolbar.TButton").pack(pady=10)

    def delete_notebook(self):
        """Delete current notebook"""
        if self.current_notebook == "默认":
            import tkinter.messagebox as messagebox
            messagebox.showwarning(self.tr("warning"), self.tr("no_delete_def"))
            return

        t = self.current_theme_colors
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr("confirm_del"))
        dialog.geometry("360x130")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=t["bg"])

        msg = self.tr("confirm_del_msg").format(self.current_notebook)
        tk.Label(dialog, text=msg, bg=t["bg"], fg=t["fg"],
                 font=(SYSTEM_FONT, self.ui_font_size), wraplength=320,
                 justify="center").pack(pady=(15, 10))

        btn_frame = tk.Frame(dialog, bg=t["bg"])
        btn_frame.pack(pady=5)

        def do_delete():
            dialog.destroy()
            notebook_path = self.get_notebook_path()
            self.current_notebook = "默认"
            shutil.rmtree(notebook_path)
            self.update_notebook_menu()
            self.refresh_notebook_listbox(self.notebook_search_var.get())
            self.switch_notebook("默认")

        ttk.Button(btn_frame, text=self.tr("cancel"), command=dialog.destroy,
                   style="Toolbar.TButton").pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text=self.tr("confirm"), command=do_delete,
                   style="Toolbar.TButton").pack(side=tk.LEFT, padx=10)

    def export_notebook(self, notebook_name=None):
        """Export a notebook as a .zip file"""
        from tkinter import filedialog
        if notebook_name is None:
            notebook_name = self.current_notebook

        # Save current notebook before export
        if notebook_name == self.current_notebook:
            self.save_notes(quick=True)

        nb_path = os.path.join(self.notebooks_dir, notebook_name)
        if not os.path.isdir(nb_path):
            return

        default_name = f"{notebook_name}.zip"
        out_path = filedialog.asksaveasfilename(
            title=self.tr("export_nb"),
            initialfile=default_name,
            defaultextension=".zip",
            filetypes=[("ZIP", "*.zip")],
            parent=self.root)
        if not out_path:
            return

        with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for dirpath, dirnames, filenames in os.walk(nb_path):
                for fn in filenames:
                    abs_file = os.path.join(dirpath, fn)
                    arc_name = os.path.relpath(abs_file, nb_path)
                    zf.write(abs_file, arc_name)

        # Show lightweight confirmation
        t = self.current_theme_colors
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr("export_nb"))
        dialog.geometry("400x100")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=t["bg"])
        tk.Label(dialog, text=self.tr("export_ok").format(out_path),
                 bg=t["bg"], fg=t["fg"], font=(SYSTEM_FONT, self.ui_font_size),
                 wraplength=360, justify="center").pack(pady=(15, 5))
        ttk.Button(dialog, text=self.tr("confirm"), command=dialog.destroy,
                   style="Toolbar.TButton").pack(pady=5)

    def import_notebook(self):
        """Import a notebook from a .zip file"""
        from tkinter import filedialog
        zip_path = filedialog.askopenfilename(
            title=self.tr("import_nb"),
            filetypes=[("ZIP", "*.zip")],
            parent=self.root)
        if not zip_path:
            return

        t = self.current_theme_colors
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                names = zf.namelist()
                # Determine notebook name from zip filename
                nb_name = os.path.splitext(os.path.basename(zip_path))[0]

                # If notebook already exists, append a number
                base_name = nb_name
                counter = 1
                while nb_name in self.get_notebooks_list():
                    nb_name = f"{base_name}_{counter}"
                    counter += 1

                nb_path = os.path.join(self.notebooks_dir, nb_name)
                os.makedirs(nb_path, exist_ok=True)

                # Extract — handle both flat (notes.txt at root) and nested layouts
                # Check if files are inside a subdirectory
                has_subdir = all('/' in n for n in names if n and not n.endswith('/'))
                if has_subdir:
                    # Files are nested under a folder, strip the common prefix
                    prefix = os.path.commonpath([n for n in names if not n.endswith('/')])
                    for member in names:
                        if member.endswith('/'):
                            continue
                        rel = os.path.relpath(member, prefix)
                        target = os.path.join(nb_path, rel)
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with zf.open(member) as src, open(target, 'wb') as dst:
                            dst.write(src.read())
                else:
                    zf.extractall(nb_path)

                # Ensure attachments dir exists
                attach_dir = os.path.join(nb_path, self.attachments_dir)
                os.makedirs(attach_dir, exist_ok=True)

            self.update_notebook_menu()
            self.refresh_notebook_listbox(self.notebook_search_var.get())
            self.switch_notebook(nb_name)

            # Confirmation
            dialog = tk.Toplevel(self.root)
            dialog.title(self.tr("import_nb"))
            dialog.geometry("350x90")
            dialog.transient(self.root)
            dialog.grab_set()
            dialog.configure(bg=t["bg"])
            tk.Label(dialog, text=self.tr("import_ok").format(nb_name),
                     bg=t["bg"], fg=t["fg"], font=(SYSTEM_FONT, self.ui_font_size)).pack(pady=(15, 5))
            ttk.Button(dialog, text=self.tr("confirm"), command=dialog.destroy,
                       style="Toolbar.TButton").pack(pady=5)

        except Exception as e:
            import tkinter.messagebox as messagebox
            messagebox.showerror(self.tr("warning"), self.tr("import_err").format(str(e)),
                                 parent=self.root)

    def indent_text(self):
        """Indent selected lines or current line by 4 spaces"""
        # Check if there's a selection
        if self.text_area.tag_ranges(tk.SEL):
            # Get selection range
            sel_start = self.text_area.index(tk.SEL_FIRST)
            sel_end = self.text_area.index(tk.SEL_LAST)

            # Get line numbers
            start_line = int(sel_start.split('.')[0])
            end_line = int(sel_end.split('.')[0])

            # Add 4 spaces to the beginning of each selected line
            for line_num in range(start_line, end_line + 1):
                self.text_area.insert(f"{line_num}.0", "    ")

            # Restore selection
            self.text_area.tag_remove(tk.SEL, "1.0", tk.END)
            self.text_area.tag_add(tk.SEL, f"{start_line}.0", f"{end_line}.end")
        else:
            # No selection - indent current line
            cursor_pos = self.text_area.index(tk.INSERT)
            line_num = cursor_pos.split('.')[0]
            self.text_area.insert(f"{line_num}.0", "    ")

    def reload_display(self):
        """Reload display with new settings"""
        # Save current content
        content = self.get_content_with_markers()

        # Clear text area
        self.text_area.delete("1.0", tk.END)

        # Clear image references and URL tags
        self.images.clear()
        self.url_tags.clear()
        self._url_preview_tags.clear()

        # Reload content
        self.load_content_with_images(content)

    def cleanup_orphaned_attachments(self):
        """Clean up attachments that are not referenced in notes"""
        content = self.get_content_with_markers()
        self.cleanup_unused_attachments(content)
        self.cleanup_filename_map()

    def cleanup_filename_map(self):
        """Remove entries from filename_map that don't have corresponding files"""
        if not self.filename_map:
            return

        attachments_path = self.get_attachments_path()
        keys_to_remove = []
        for internal_filename in self.filename_map:
            filepath = os.path.join(attachments_path, internal_filename)
            if not os.path.exists(filepath):
                keys_to_remove.append(internal_filename)
                print(f"Removing orphaned map entry: {internal_filename}")

        for key in keys_to_remove:
            del self.filename_map[key]

        if keys_to_remove:
            self.save_filename_map()

    def increase_font(self):
        self.current_font_size += 2
        self.update_font()

    def decrease_font(self):
        if self.current_font_size > 8:
            self.current_font_size -= 2
            self.update_font()

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)

                    # 加载当前笔记本（需要在其他配置之前）
                    notebook = config.get("current_notebook", "默认")
                    if notebook in self.get_notebooks_list():
                        self.current_notebook = notebook
                    else:
                        self.current_notebook = "默认"

                    # 同步更新 UI 显示的笔记本名称
                    self.notebook_var.set(self.current_notebook)

                    # 确保当前笔记本的附件目录存在
                    self.ensure_attachments_dir()
                    self.load_filename_map()

                    # 加载置顶状态
                    is_top = config.get("always_on_top", False)
                    self.always_on_top.set(is_top)
                    self.toggle_topmost()

                    # 加载字体大小
                    self.current_font_size = config.get("font_size", 12)
                    self.update_font()

                    # 加载图片大小
                    self.max_image_width = config.get("image_width", 400)

                    # 加载图标大小
                    self.icon_font_size = config.get("icon_size", 24)

                    # 加载UI字号（未保存过则保留自动检测的合适大小）
                    self.ui_font_size = config.get("ui_font_size", self.ui_font_size)

                    # 加载文本边距
                    self.text_padding = config.get("text_padding", 10)
                    self.text_area.config(padx=self.text_padding)

                    # 加载是否显示图片名
                    self.show_image_name.set(config.get("show_image_name", True))

                    # 加载窗口大小和位置
                    geometry = config.get("geometry")
                    if geometry:
                        self.root.geometry(geometry)

                    # 加载侧边栏宽度（恢复用户上次拖拽设置的宽度）
                    self._sidebar_width = config.get("sidebar_width", 150)
                    try:
                        self.main_paned.paneconfigure(self.sidebar_frame,
                                                       width=self._sidebar_width)
                    except Exception as e:
                        print(f"Error restoring sidebar width: {e}")

                    # 加载侧边栏状态
                    sidebar_visible = config.get("sidebar_visible", True)
                    if not sidebar_visible:
                        # 需要隐藏侧边栏
                        self.sidebar_visible = True  # 先设为True，让toggle_sidebar能正确切换
                        self.toggle_sidebar()

                    # 加载回收框状态
                    show_recycle = config.get("show_recycle_box", True)
                    self.show_recycle_box.set(show_recycle)
                    if not show_recycle:
                        self.recycle_frame.pack_forget()

                    # 加载目录面板宽度和可见状态
                    self._outline_width = config.get("outline_width", 240)
                    self._outline_height = config.get("outline_height", 0)
                    self._outline_font_size = config.get("outline_font_size", 12)
                    if hasattr(self, 'outline_text'):
                        self._apply_outline_font_tags()
                    self._outline_restore = config.get("outline_visible", False)

                    # 加载语言
                    lang = config.get("language", "zh")
                    if lang in ("zh", "en"):
                        self.language = lang
                        self._refresh_all_text()

                    # 加载主题
                    theme = config.get("theme", "dark")
                    if theme in self.THEMES:
                        self.apply_theme(theme)
                    else:
                        self.apply_theme("dark")

            except Exception as e:
                print(f"Error loading config: {e}")
        else:
            # No config file - apply default dark theme
            self.apply_theme("dark")

    def save_config(self):
        # 仅在侧边栏可见时更新宽度，避免隐藏时把宽度存成 0
        if getattr(self, 'sidebar_visible', True) and hasattr(self, 'sidebar_frame'):
            try:
                w = self.sidebar_frame.winfo_width()
                if w > 1:
                    self._sidebar_width = w
            except Exception:
                pass
        config = {
            "always_on_top": self.always_on_top.get(),
            "font_size": self.current_font_size,
            "image_width": self.max_image_width,
            "icon_size": self.icon_font_size,
            "ui_font_size": self.ui_font_size,
            "text_padding": self.text_padding,
            "show_image_name": self.show_image_name.get(),
            "geometry": self.root.geometry(),
            "current_notebook": self.current_notebook,
            "sidebar_visible": self.sidebar_visible,
            "sidebar_width": getattr(self, '_sidebar_width', 150),
            "show_recycle_box": self.show_recycle_box.get(),
            "theme": self.current_theme,
            "outline_width": self._outline_width,
            "outline_height": self._outline_height,
            "outline_font_size": self._outline_font_size,
            "outline_visible": self._outline_visible,
            "language": self.language
        }
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f)
        except Exception as e:
            print(f"Error saving config: {e}")

    def load_notes(self):
        """Load notes and restore embedded images from markers"""
        note_path = self.get_note_file_path()
        if os.path.exists(note_path):
            try:
                with open(note_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    self.load_content_with_images(content)
            except Exception as e:
                print(f"Error loading notes: {e}")
        # Update window title
        self.root.title(f"Quick Note Board - {self.current_notebook}")
        # Initialize last_saved_content to prevent unnecessary auto-save on startup
        self.last_saved_content = self.get_content_with_markers()
        # Clear Tk native undo stack (initial load is not undoable)
        self.text_area.edit_reset()

    def load_content_with_images(self, content, use_thumbnails=False):
        """Parse content and restore images from markers

        Args:
            use_thumbnails: If True, load images as small thumbnails for fast switching
        """
        # Clean up stale bullet dots (•) that were erroneously inserted by a prior bug
        content = re.sub(r'^(\s*[-*])•+', r'\1', content, flags=re.MULTILINE)
        content = re.sub(r'^(\s*)•+(\s)', r'\1*\2', content, flags=re.MULTILINE)

        # Quick check: if no markers, just insert text directly (fast path)
        if '[IMAGE:' not in content and '[FILE:' not in content and '[STRIKE]' not in content and '[HL:' not in content:
            # Simple text only - insert directly without URL processing for speed
            self.text_area.insert(tk.END, content)
            self.apply_markdown_formatting()
            return

        # Pattern to match [IMAGE:filename] or [IMAGE:filename:width], [FILE:filename], and [STRIKE]/[/STRIKE]
        image_pattern = re.compile(r'\[IMAGE:([^:\]]+)(?::(\d+))?\]')
        file_pattern = re.compile(r'\[FILE:([^\]]+)\]')
        hl_pattern = re.compile(r'\[HL:(\w+)\]')

        # Split content by markers while keeping the markers
        parts = re.split(r'(\[IMAGE:[^\]]+\]|\[FILE:[^\]]+\]|\[STRIKE\]|\[/STRIKE\]|\[HL:\w+\]|\[/HL\])', content)

        in_strikethrough = False
        in_highlight = None  # None or color name
        for part in parts:
            if not part:
                continue

            if part == '[STRIKE]':
                in_strikethrough = True
                continue
            elif part == '[/STRIKE]':
                in_strikethrough = False
                continue

            hl_match = hl_pattern.match(part)
            if hl_match:
                in_highlight = hl_match.group(1)
                continue
            elif part == '[/HL]':
                in_highlight = None
                continue

            image_match = image_pattern.match(part)
            file_match = file_pattern.match(part)

            if image_match:
                filename = image_match.group(1)
                width_str = image_match.group(2)
                width = int(width_str) if width_str else None
                filepath = os.path.join(self.get_attachments_path(), filename)
                if os.path.exists(filepath):
                    self.insert_image_at_cursor(filepath, filename, tk.END, width, thumbnail=use_thumbnails)
                else:
                    # Image file missing, insert marker as text
                    self.text_area.insert(tk.END, part)
            elif file_match:
                filename = file_match.group(1)
                filepath = os.path.join(self.get_attachments_path(), filename)
                if os.path.exists(filepath):
                    self.insert_file_link_at_end(filename)
                else:
                    # File missing, insert marker as text
                    self.text_area.insert(tk.END, part)
            else:
                # Regular text — apply strikethrough and/or highlight tags
                if in_strikethrough or in_highlight:
                    start = self.text_area.index(tk.END + "-1c")
                    self.text_area.insert(tk.END, part)
                    end = self.text_area.index(tk.END + "-1c")
                    if in_strikethrough:
                        self.text_area.tag_add("strikethrough", start, end)
                    if in_highlight:
                        self.text_area.tag_add(f"highlight_{in_highlight}", start, end)
                else:
                    self.text_area.insert(tk.END, part)

        self.apply_markdown_formatting()

    def insert_file_link_at_end(self, internal_filename):
        """Insert file link at end of text (for loading)"""
        # Try video thumbnail preview first
        if self._is_video_file(internal_filename):
            if self._insert_video_preview(internal_filename, position=tk.END):
                return

        # Get display name (original filename)
        display_name = self.get_display_name(internal_filename)
        # Get file icon
        icon = self.get_file_icon(display_name)

        # Insert icon with larger font
        icon_start = self.text_area.index(tk.END + "-1c")
        self.text_area.insert(tk.END, icon)
        icon_end = self.text_area.index(tk.END + "-1c")

        # Tag for icon with larger font
        icon_tag = f"icon_{internal_filename}"
        self.text_area.tag_add(icon_tag, icon_start, icon_end)
        self.text_area.tag_config(icon_tag, font=(SYSTEM_FONT, self.icon_font_size))

        # Insert space and filename
        self.text_area.insert(tk.END, " ")
        text_start = self.text_area.index(tk.END + "-1c")
        self.text_area.insert(tk.END, display_name)
        text_end = self.text_area.index(tk.END + "-1c")

        # Add tag for text styling and click handling
        tag_name = f"file_{internal_filename}"
        self.text_area.tag_add(tag_name, text_start, text_end)
        self.text_area.tag_config(tag_name, foreground=self.current_theme_colors["accent_green"], underline=False)

        # Also make icon clickable
        self.text_area.tag_bind(icon_tag, "<Button-1>", lambda e: self.select_file(internal_filename))
        self.text_area.tag_bind(icon_tag, "<Double-Button-1>", lambda e: self.open_file(internal_filename))
        self.text_area.tag_bind(icon_tag, "<Button-2>", lambda e: self.show_file_menu(e, internal_filename))
        self.text_area.tag_bind(icon_tag, "<Button-3>", lambda e: self.show_file_menu(e, internal_filename))
        self.text_area.tag_bind(icon_tag, "<Enter>", lambda e: self.text_area.config(cursor="hand2"))
        self.text_area.tag_bind(icon_tag, "<Leave>", lambda e: self.text_area.config(cursor=""))
        # Single click to select file (for copy)
        self.text_area.tag_bind(tag_name, "<Button-1>", lambda e: self.select_file(internal_filename))
        # Double-click to open file
        self.text_area.tag_bind(tag_name, "<Double-Button-1>", lambda e: self.open_file(internal_filename))
        # Right-click to show context menu
        self.text_area.tag_bind(tag_name, "<Button-2>", lambda e: self.show_file_menu(e, internal_filename))  # macOS
        self.text_area.tag_bind(tag_name, "<Button-3>", lambda e: self.show_file_menu(e, internal_filename))  # Windows/Linux
        self.text_area.tag_bind(tag_name, "<Enter>", lambda e: self.text_area.config(cursor="hand2"))
        self.text_area.tag_bind(tag_name, "<Leave>", lambda e: self.text_area.config(cursor=""))

    def save_notes(self, quick=False):
        """Save notes with image markers for embedded images

        Args:
            quick: If True, skip backup and cleanup for faster save (used during notebook switch)
        """
        # If current notebook has an open viewer, sync from it
        if not quick:
            for viewer in list(self._notebook_viewers):
                try:
                    if viewer.winfo_exists() and viewer._nb_name == self.current_notebook:
                        self._sync_from_viewer(viewer)
                        break
                except Exception as e:
                    print(f"Error syncing from viewer: {e}")
            # Save all other open floating viewers
            for viewer in list(self._notebook_viewers):
                try:
                    if viewer.winfo_exists() and viewer._nb_name != self.current_notebook:
                        self._viewer_save(viewer)
                except Exception as e:
                    print(f"Error saving viewer: {e}")

        # In quick mode, skip if content not modified
        if quick and not self.content_modified:
            return

        try:
            # Create backup before saving (skip in quick mode)
            if not quick:
                self.backup_notes()

            # Build content with image markers
            content = self.get_content_with_markers()
            note_path = self.get_note_file_path()

            # ── Data-loss guard ──────────────────────────────────────────
            # Never overwrite a note that has real content on disk with an
            # empty/whitespace editor. A transient blank editor (during a
            # notebook switch, a failed reload, or a stray clear) must not be
            # allowed to zero the file. Leave the on-disk content untouched.
            if not content.strip():
                try:
                    if os.path.exists(note_path) and os.path.getsize(note_path) > 0:
                        with open(note_path, "r", encoding="utf-8") as f:
                            existing = f.read()
                        if existing.strip():
                            print(f"save_notes: refused to overwrite non-empty "
                                  f"note '{self.current_notebook}' with empty "
                                  f"content (skipped to prevent data loss).")
                            return
                except Exception as e:
                    print(f"save_notes empty-guard error: {e}")

            with open(note_path, "w", encoding="utf-8") as f:
                f.write(content)

            # Update last_saved_content to prevent duplicate saves
            self.last_saved_content = content

            # Mark content as saved
            self.content_modified = False

            # Clean up unused attachments (skip in quick mode)
            if not quick:
                self.cleanup_unused_attachments(content)

            # Refresh sidebar so the just-edited notebook re-sorts to the top
            # (non-shortcut notebooks are ordered by most recent modification)
            try:
                search_text = self.notebook_search_var.get() if hasattr(self, 'notebook_search_var') else ""
                self.refresh_notebook_listbox(search_text)
            except Exception as e:
                print(f"Error refreshing notebook list after save: {e}")
        except Exception as e:
            print(f"Error saving notes: {e}")

    def cleanup_unused_attachments(self, content):
        """Remove attachments that are no longer referenced in notes"""
        try:
            # Find all referenced files in content
            # Support both [IMAGE:filename] and [IMAGE:filename:width] formats
            import re
            image_refs = set(re.findall(r'\[IMAGE:([^:\]]+)(?::\d+)?\]', content))
            file_refs = set(re.findall(r'\[FILE:([^\]]+)\]', content))
            referenced_files = image_refs | file_refs

            # Also check undo/redo stacks — files there may be needed for undo/redo
            for stack_content, _ in self.undo_stack + self.redo_stack:
                referenced_files.update(re.findall(r'\[IMAGE:([^:\]]+)(?::\d+)?\]', stack_content))
                referenced_files.update(re.findall(r'\[FILE:([^\]]+)\]', stack_content))

            # Get all files in attachments directory
            attachments_path = self.get_attachments_path()
            if not os.path.exists(attachments_path):
                return

            for filename in os.listdir(attachments_path):
                # Skip special files
                if filename.startswith('.') or filename == 'filename_map.json':
                    continue

                # Skip thumbnail cache files (video and image thumbnails)
                if filename.startswith('_thumb_'):
                    continue

                # If file is not referenced, delete it
                if filename not in referenced_files:
                    filepath = os.path.join(attachments_path, filename)
                    try:
                        if os.path.isdir(filepath):
                            shutil.rmtree(filepath)
                        else:
                            os.remove(filepath)
                        print(f"Removed unused attachment: {filename}")

                        # Also remove from filename_map
                        if filename in self.filename_map:
                            del self.filename_map[filename]

                        # Remove associated video thumbnail cache
                        thumb_cache = os.path.join(attachments_path, f"_thumb_{filename}.png")
                        if os.path.exists(thumb_cache):
                            os.remove(thumb_cache)
                    except Exception as e:
                        print(f"Error removing {filename}: {e}")

            # Save updated filename_map
            self.save_filename_map()

        except Exception as e:
            print(f"Error cleaning up attachments: {e}")

    def backup_notes(self):
        """Create a backup of notes before saving"""
        note_path = self.get_note_file_path()
        if os.path.exists(note_path):
            try:
                backup_dir = "backups"
                if not os.path.exists(backup_dir):
                    os.makedirs(backup_dir)

                # Keep last 10 backups per notebook
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = os.path.join(backup_dir, f"{self.current_notebook}_backup_{timestamp}.txt")
                shutil.copy2(note_path, backup_file)

                # Clean old backups for this notebook, keep only last 10
                prefix = f"{self.current_notebook}_backup_"
                backups = sorted([f for f in os.listdir(backup_dir) if f.startswith(prefix)])
                while len(backups) > 10:
                    os.remove(os.path.join(backup_dir, backups.pop(0)))
            except Exception as e:
                print(f"Error creating backup: {e}")

    def get_content_with_markers(self):
        """Get text content, replacing embedded images and file links with markers"""
        result = []

        # Omit tag=True to avoid dumping thousands of md_* tag events.
        # Text chunks are still split at tag boundaries by Tk internally,
        # so skip-range logic remains correct.
        dump_data = self.text_area.dump("1.0", tk.END, text=True, image=True)

        # Helper: parse "line.col" string to (int, int) tuple for fast comparison
        def _idx(s):
            line, col = s.split(".")
            return (int(line), int(col))

        # Build skip ranges and file markers using pure-Python tuples
        skip_ranges = []       # List of ((l,c), (l,c)) tuples
        file_markers = {}      # (l,c) tuple -> marker string
        skip_range_ends = {}   # start (l,c) -> end (l,c), for file marker ranges

        for tag in self.text_area.tag_names():
            if tag.startswith("icon_"):
                internal_filename = tag[5:]
                ranges = self.text_area.tag_ranges(tag)
                if ranges:
                    icon_start = str(ranges[0])
                    file_tag = f"file_{internal_filename}"
                    file_ranges = self.text_area.tag_ranges(file_tag)
                    if file_ranges:
                        file_end = str(file_ranges[1])
                        s, e = _idx(icon_start), _idx(file_end)
                        skip_ranges.append((s, e))
                        file_markers[s] = f"[FILE:{internal_filename}]"
                        skip_range_ends[s] = e
            elif tag.startswith("imgname_"):
                internal_filename = tag[8:]
                ranges = self.text_area.tag_ranges(tag)
                if ranges:
                    name_start = str(ranges[0])
                    name_end = str(ranges[1])
                    prev_idx = self.text_area.index(f"{name_start}-1c")
                    if self.text_area.get(prev_idx) == "\n":
                        name_start = prev_idx
                    skip_ranges.append((_idx(name_start), _idx(name_end)))
            elif tag.startswith("url_preview_"):
                ranges = self.text_area.tag_ranges(tag)
                for ri in range(0, len(ranges), 2):
                    s = _idx(str(ranges[ri]))
                    e = _idx(str(ranges[ri + 1]))
                    skip_ranges.append((s, e))

        # Sort skip ranges by start for efficient checking
        skip_ranges.sort()

        # Pre-compute strikethrough boundaries (replaces tag=True for strikethrough)
        strike_starts = set()
        strike_ends = set()
        strike_raw = self.text_area.tag_ranges("strikethrough")
        for si in range(0, len(strike_raw), 2):
            strike_starts.add(_idx(str(strike_raw[si])))
            strike_ends.add(_idx(str(strike_raw[si + 1])))

        # Pre-compute highlight boundaries per color
        hl_starts = {}  # pos -> color
        hl_ends = {}    # pos -> color
        for color in self.HIGHLIGHT_NAMES:
            raw = self.text_area.tag_ranges(f"highlight_{color}")
            for hi in range(0, len(raw), 2):
                hl_starts[_idx(str(raw[hi]))] = color
                hl_ends[_idx(str(raw[hi + 1]))] = color

        def is_in_skip_range(t):
            for s, e in skip_ranges:
                if s <= t < e:
                    return True
                if s > t:
                    break  # sorted: no later range can contain t
            return False

        strike_emitted_starts = set()
        strike_emitted_ends = set()
        hl_emitted_starts = set()
        hl_emitted_ends = set()

        i = 0
        while i < len(dump_data):
            key, value, index = dump_data[i]
            t = _idx(index)

            # Check if we should insert a file marker
            marker = file_markers.get(t)
            if marker:
                result.append(marker)
                end_t = skip_range_ends[t]
                # Skip all items in this range
                i += 1
                while i < len(dump_data):
                    if _idx(dump_data[i][2]) >= end_t:
                        break
                    i += 1
                continue

            # Skip content in skip ranges (image labels without file markers)
            if is_in_skip_range(t):
                i += 1
                continue

            # Emit strikethrough markers at tag boundaries
            if t in strike_ends and t not in strike_emitted_ends:
                result.append('[/STRIKE]')
                strike_emitted_ends.add(t)
            if t in strike_starts and t not in strike_emitted_starts:
                result.append('[STRIKE]')
                strike_emitted_starts.add(t)

            # Emit highlight markers at tag boundaries
            if t in hl_ends and t not in hl_emitted_ends:
                result.append('[/HL]')
                hl_emitted_ends.add(t)
            if t in hl_starts and t not in hl_emitted_starts:
                result.append(f'[HL:{hl_starts[t]}]')
                hl_emitted_starts.add(t)

            if key == 'text':
                result.append(value)
            elif key == 'image':
                if value.startswith("img_"):
                    filename = value[4:]
                    # Strip duplicate suffix (e.g. "photo.png#2" → "photo.png")
                    if '#' in filename:
                        filename = filename[:filename.index('#')]
                    if filename in self.image_widths:
                        width = self.image_widths[filename]
                        result.append(f"[IMAGE:{filename}:{width}]")
                    else:
                        result.append(f"[IMAGE:{filename}]")

            i += 1

        # Emit any remaining end markers (e.g. at document end)
        for pos in sorted(strike_ends - strike_emitted_ends):
            result.append('[/STRIKE]')
        for pos in sorted(set(hl_ends) - hl_emitted_ends):
            result.append('[/HL]')

        content = "".join(result)
        if content.endswith("\n"):
            content = content[:-1]
        return content

    def _confirm_quit(self, event=None):
        """Ask the user to confirm before quitting (Cmd+Q on macOS).

        Cmd+Q sits next to common shortcuts like Cmd+W/Cmd+A and is easy to
        hit by accident, so we always require an explicit confirmation here.
        """
        import tkinter.messagebox as messagebox
        try:
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass
        if messagebox.askyesno(
            self.tr("quit_confirm_title"),
            self.tr("quit_confirm_msg"),
            parent=self.root,
            default="no",
        ):
            self.on_closing()
        return "break"

    def on_closing(self):
        for viewer in list(self._notebook_viewers):
            try:
                self._viewer_save(viewer)
                viewer.destroy()
            except:
                pass
        self._notebook_viewers.clear()
        self.save_notes()
        self.save_config()
        self.root.destroy()

    def set_window_icon(self):
        """Set the window icon"""
        icon_path = os.path.join(os.path.dirname(__file__), "assets", "quick_note_board.png")
        if os.path.exists(icon_path) and PIL_AVAILABLE:
            try:
                icon_image = Image.open(icon_path)
                icon_photo = ImageTk.PhotoImage(icon_image)
                self.root.iconphoto(True, icon_photo)
                # Keep reference to prevent garbage collection
                self.icon_photo = icon_photo
            except Exception as e:
                print(f"Error setting icon: {e}")

    def ensure_attachments_dir(self):
        """Create attachments directory if it doesn't exist"""
        attachments_path = self.get_attachments_path()
        if not os.path.exists(attachments_path):
            os.makedirs(attachments_path)

    def load_filename_map(self):
        """Load filename mapping from JSON file"""
        attachments_path = self.get_attachments_path()
        map_file = os.path.join(attachments_path, "filename_map.json")
        self.filename_map = {}  # Clear before loading
        if os.path.exists(map_file):
            try:
                with open(map_file, "r", encoding="utf-8") as f:
                    self.filename_map = json.load(f)
            except Exception as e:
                print(f"Error loading filename map: {e}")

    def save_filename_map(self):
        """Save filename mapping to JSON file"""
        attachments_path = self.get_attachments_path()
        map_file = os.path.join(attachments_path, "filename_map.json")
        try:
            with open(map_file, "w", encoding="utf-8") as f:
                json.dump(self.filename_map, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving filename map: {e}")

    def _load_url_title_cache(self):
        """Load URL title cache from JSON file."""
        cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "url_titles_cache.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    self._url_title_cache = json.load(f)
            except Exception:
                self._url_title_cache = {}

    def _save_url_title_cache(self):
        """Save URL title cache to JSON file."""
        cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "url_titles_cache.json")
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(self._url_title_cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_display_name(self, internal_name):
        """Get original filename for display"""
        info = self.filename_map.get(internal_name)
        if isinstance(info, dict):
            return info.get("name", internal_name)
        elif isinstance(info, str):
            return info  # 兼容旧格式
        return internal_name

    def get_original_path(self, internal_name):
        """Get original file path"""
        info = self.filename_map.get(internal_name)
        if isinstance(info, dict):
            return info.get("path")
        return None

    def get_file_icon(self, filename):
        """Get emoji icon based on file extension"""
        ext = os.path.splitext(filename)[1].lower()

        if _IS_LINUX:
            # Plain-text icons for Linux (X11 bitmap fonts lack emoji)
            if ext in {'.mp4', '.m4v', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm'}:
                return '▶'
            elif ext in {'.mp3', '.wav', '.aac', '.flac', '.m4a', '.ogg', '.wma'}:
                return '♪'
            elif ext in {'.doc', '.docx', '.rtf', '.odt'}:
                return '¶'
            elif ext == '.pdf':
                return '¶'
            elif ext in {'.xls', '.xlsx', '.csv', '.ods'}:
                return '#'
            elif ext in {'.ppt', '.pptx', '.odp', '.key'}:
                return '▶'
            elif ext in {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'}:
                return '■'
            elif ext in {'.py', '.js', '.html', '.css', '.java', '.c', '.cpp', '.h', '.swift', '.go', '.rs'}:
                return '<>'
            elif ext in {'.txt', '.md', '.json', '.xml', '.yaml', '.yml'}:
                return '='
            elif ext in {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.ico'}:
                return '★'
            elif ext in {'.exe', '.app', '.dmg', '.pkg', '.deb', '.rpm'}:
                return '*'
            else:
                return '-'

        # Video files
        if ext in {'.mp4', '.m4v', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm'}:
            return '🎬'
        # Audio files
        elif ext in {'.mp3', '.wav', '.aac', '.flac', '.m4a', '.ogg', '.wma'}:
            return '🎵'
        # Document files
        elif ext in {'.doc', '.docx', '.rtf', '.odt'}:
            return '📝'
        # PDF
        elif ext == '.pdf':
            return '📕'
        # Spreadsheet
        elif ext in {'.xls', '.xlsx', '.csv', '.ods'}:
            return '📊'
        # Presentation
        elif ext in {'.ppt', '.pptx', '.odp', '.key'}:
            return '📽️'
        # Archive
        elif ext in {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'}:
            return '📦'
        # Code
        elif ext in {'.py', '.js', '.html', '.css', '.java', '.c', '.cpp', '.h', '.swift', '.go', '.rs'}:
            return '💻'
        # Text
        elif ext in {'.txt', '.md', '.json', '.xml', '.yaml', '.yml'}:
            return '📄'
        # Image (non-embedded)
        elif ext in {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.ico'}:
            return '🖼️'
        # Executable
        elif ext in {'.exe', '.app', '.dmg', '.pkg', '.deb', '.rpm'}:
            return '⚙️'
        # Default
        else:
            return '📎'

    VIDEO_EXTENSIONS = {'.mp4', '.m4v', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm'}

    def _is_video_file(self, filename):
        """Check if filename is a video file based on extension"""
        ext = os.path.splitext(filename)[1].lower()
        return ext in self.VIDEO_EXTENSIONS

    def _generate_video_thumbnail(self, video_filepath):
        """Generate a thumbnail image for a video file with play button and duration overlay.

        Uses macOS qlmanage for frame extraction and mdls for duration.
        Returns PIL Image or None on failure.
        """
        if not PIL_AVAILABLE or platform.system() != "Darwin":
            return None

        import tempfile
        tmp_dir = tempfile.mkdtemp()
        try:
            # Extract a frame using qlmanage
            result = subprocess.run(
                ["qlmanage", "-t", "-s", "600", "-o", tmp_dir, video_filepath],
                capture_output=True, timeout=5
            )
            if result.returncode != 0:
                return None

            # qlmanage outputs to tmp_dir/<filename>.png
            thumb_files = [f for f in os.listdir(tmp_dir) if f.endswith(".png")]
            if not thumb_files:
                return None

            frame = Image.open(os.path.join(tmp_dir, thumb_files[0])).convert("RGBA")

            # Get video duration using mdls
            duration_text = None
            try:
                result = subprocess.run(
                    ["mdls", "-name", "kMDItemDurationSeconds", video_filepath],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    # Parse "kMDItemDurationSeconds = 123.456"
                    for line in result.stdout.strip().split("\n"):
                        if "=" in line:
                            val = line.split("=")[1].strip()
                            if val != "(null)":
                                secs = int(float(val))
                                mins, secs = divmod(secs, 60)
                                hours, mins = divmod(mins, 60)
                                if hours > 0:
                                    duration_text = f"{hours}:{mins:02d}:{secs:02d}"
                                else:
                                    duration_text = f"{mins}:{secs:02d}"
            except Exception:
                pass  # Duration is optional

            # Draw play button overlay (center)
            overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            w, h = frame.size
            circle_r = min(w, h) // 8
            cx, cy = w // 2, h // 2

            # Semi-transparent dark circle
            draw.ellipse(
                [cx - circle_r, cy - circle_r, cx + circle_r, cy + circle_r],
                fill=(0, 0, 0, 160)
            )

            # White triangle (play icon) inside circle
            tri_size = circle_r * 0.6
            # Offset right slightly for visual centering of triangle
            tri_cx = cx + int(tri_size * 0.1)
            triangle = [
                (tri_cx - int(tri_size * 0.4), cy - int(tri_size * 0.6)),
                (tri_cx - int(tri_size * 0.4), cy + int(tri_size * 0.6)),
                (tri_cx + int(tri_size * 0.6), cy),
            ]
            draw.polygon(triangle, fill=(255, 255, 255, 230))

            # Duration badge (bottom-right)
            if duration_text:
                try:
                    font = ImageFont.truetype("/System/Library/Fonts/SFCompact.ttf", 18)
                except Exception:
                    try:
                        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
                    except Exception:
                        font = ImageFont.load_default()

                bbox = draw.textbbox((0, 0), duration_text, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                pad_x, pad_y = 8, 4
                margin = 10
                rx = w - margin - tw - pad_x * 2
                ry = h - margin - th - pad_y * 2

                # Rounded rect background
                draw.rounded_rectangle(
                    [rx, ry, rx + tw + pad_x * 2, ry + th + pad_y * 2],
                    radius=6, fill=(0, 0, 0, 180)
                )
                draw.text((rx + pad_x, ry + pad_y), duration_text, fill=(255, 255, 255, 240), font=font)

            # Composite overlay onto frame
            frame = Image.alpha_composite(frame, overlay)
            return frame.convert("RGB")

        except subprocess.TimeoutExpired:
            return None
        except Exception as e:
            print(f"Error generating video thumbnail: {e}")
            return None
        finally:
            # Clean up temp directory
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass

    def _get_video_thumbnail(self, internal_filename):
        """Get video thumbnail with caching. Returns PIL Image or None."""
        # In-memory cache first (fastest, used during undo/redo)
        if internal_filename in self._video_thumb_cache:
            return self._video_thumb_cache[internal_filename].copy()

        attachments_path = self.get_attachments_path()
        video_path = os.path.join(attachments_path, internal_filename)
        if not os.path.exists(video_path):
            return None

        cache_name = f"_thumb_{internal_filename}.png"
        cache_path = os.path.join(attachments_path, cache_name)

        # Disk cache second
        if os.path.exists(cache_path):
            if os.path.getmtime(cache_path) >= os.path.getmtime(video_path):
                try:
                    thumb = Image.open(cache_path)
                    thumb.load()  # Force load into memory
                    self._video_thumb_cache[internal_filename] = thumb
                    return thumb.copy()
                except Exception:
                    pass  # Corrupt cache, regenerate

        # Generate thumbnail (slowest, only on first paste)
        thumb = self._generate_video_thumbnail(video_path)
        if thumb is not None:
            try:
                thumb.save(cache_path, "PNG")
            except Exception:
                pass  # Cache write failure is non-fatal
            self._video_thumb_cache[internal_filename] = thumb
            return thumb.copy()
        return None

    def setup_paste_binding(self):
        """Bind paste events for images and files"""
        # Bind to both Command-v (macOS) and Control-v (Windows/Linux)
        self.text_area.bind("<Command-v>", self.handle_paste)
        self.text_area.bind("<Control-v>", self.handle_paste)

        # Bind Cmd+S / Ctrl+S for quick save
        self.root.bind("<Command-s>", lambda e: self.save_notes())
        self.root.bind("<Control-s>", lambda e: self.save_notes())

        # Bind Cmd+F / Ctrl+F for text search
        self.root.bind("<Command-f>", lambda e: self._toggle_search_bar())
        self.root.bind("<Control-f>", lambda e: self._toggle_search_bar())

        # Bind Ctrl+Tab / Cmd+Tab for quick notebook switch (use bind_all for global capture)
        self.root.bind_all("<Control-Tab>", self.quick_switch_notebook)
        # Note: Command-Tab is reserved by macOS for app switching, use Control-Tab instead

    def setup_undo_redo(self):
        """Bind undo/redo keyboard shortcuts"""
        # Undo/Redo: Cmd+Z / Ctrl+Z (Shift detected inside handler for redo)
        # On macOS, Cmd+Shift+Z may match <Command-z> or <Command-Z> instead of
        # <Command-Shift-z>, so we use a unified handler that checks for Shift.
        self.text_area.bind("<Command-z>", self.handle_undo_redo)
        self.text_area.bind("<Command-Z>", self.handle_undo_redo)
        self.text_area.bind("<Control-z>", self.handle_undo_redo)
        self.text_area.bind("<Control-Z>", self.handle_undo_redo)

        # Tab indent / Shift+Tab unindent
        # Ctrl+Tab must be bound here (widget level) so it takes priority over <Tab>,
        # otherwise <Tab> matches first and "break" blocks the bind_all <Control-Tab>.
        self.text_area.bind("<Control-Tab>", self.quick_switch_notebook)
        self.text_area.bind("<Tab>", self.handle_tab)
        self.text_area.bind("<Shift-Tab>", self.handle_shift_tab)

        # Explicit redo bindings (for systems where Shift combos match correctly)
        self.text_area.bind("<Command-Shift-z>", self.redo)
        self.text_area.bind("<Command-Shift-Z>", self.redo)
        self.text_area.bind("<Control-Shift-z>", self.redo)
        self.text_area.bind("<Control-Shift-Z>", self.redo)
        self.text_area.bind("<Control-y>", self.redo)

        # Copy: Cmd+C / Ctrl+C - intercept to handle file links
        self.text_area.bind("<Command-c>", self.handle_copy)
        self.text_area.bind("<Control-c>", self.handle_copy)

        # Save state BEFORE destructive operations (delete, backspace, cut)
        self.text_area.bind("<Delete>", self.on_before_delete)
        self.text_area.bind("<BackSpace>", self.on_before_delete)
        self.text_area.bind("<Command-x>", self.on_before_cut)
        self.text_area.bind("<Control-x>", self.on_before_cut)

        # Cmd+1~5: quick line highlight
        for key, color in [("1", "green"), ("2", "yellow"), ("3", "red"), ("4", "orange"), ("5", "purple")]:
            cb = lambda e, c=color: self._toggle_line_highlight(c)
            self.text_area.bind(f"<Command-Key-{key}>", cb)
            self.text_area.bind(f"<Control-Key-{key}>", cb)

        # Save state before typing (with debounce)
        self.text_area.bind("<Key>", self.on_key_press)
        self.last_key_time = 0
        self.key_debounce_ms = 500  # Save state if no typing for 500ms

        # Auto-save configuration
        self.auto_save_delay_ms = 3000  # Auto-save 3 seconds after last modification
        self.auto_save_timer_id = None  # Timer ID for pending auto-save
        self.last_saved_content = None  # Track last saved content to avoid unnecessary saves

    def setup_strikethrough(self):
        """Configure strikethrough tag and right-click context menu for text area"""
        # Configure strikethrough tag with overstrike font and dimmed color
        self.text_area.tag_configure(
            "strikethrough",
            overstrike=True,
            foreground=self.current_theme_colors["fg_dim"]
        )

        # Configure highlight tags (spacing1/spacing3=0 so the block hugs text)
        t = self.current_theme_colors
        for color in self.HIGHLIGHT_NAMES:
            self.text_area.tag_configure(f"highlight_{color}", background=t[f"hl_{color}"],
                                         spacing1=0, spacing3=0)
        # Selection renders above highlights to avoid flicker while selecting
        try:
            self.text_area.tag_raise("sel")
        except Exception:
            pass

        # Right-click context menu on text area
        self.text_area.bind("<Button-2>", self.show_text_context_menu)  # macOS
        self.text_area.bind("<Button-3>", self.show_text_context_menu)  # Windows/Linux

    def show_text_context_menu(self, event):
        """Show context menu on right-click in text area"""
        has_selection = bool(self.text_area.tag_ranges(tk.SEL))

        if not has_selection:
            # No selection: show highlight + notebook link menu for current line
            menu = self.make_styled_menu()
            # Place cursor at right-click position
            click_idx = self.text_area.index(f"@{event.x},{event.y}")
            self.text_area.mark_set(tk.INSERT, click_idx)
            cursor_line = click_idx.split('.')[0]
            # Highlight colors for current line
            for color in self.HIGHLIGHT_NAMES:
                menu.add_command(
                    label=self.tr(f"hl_{color}"),
                    command=lambda c=color: self._toggle_line_highlight(c))
            has_hl = any(self.text_area.tag_nextrange(f"highlight_{c}", f"{cursor_line}.0", f"{cursor_line}.end")
                         for c in self.HIGHLIGHT_NAMES)
            if has_hl:
                menu.add_command(label=self.tr("remove_highlight"),
                                 command=lambda: self._toggle_line_highlight_remove(cursor_line))
            menu.add_separator()
            menu.add_command(label=self.tr("copy_nb_link"),
                             command=self.copy_notebook_link)
            menu.tk_popup(event.x_root, event.y_root)
            return

        menu = self.make_styled_menu()

        sel_start = self.text_area.index(tk.SEL_FIRST)
        tags_at_sel = self.text_area.tag_names(sel_start)

        # Strikethrough
        has_strike = "strikethrough" in tags_at_sel
        if has_strike:
            menu.add_command(label=self.tr("remove_strike"), command=self.remove_strikethrough)
        else:
            menu.add_command(label=self.tr("strikethrough"), command=self.apply_strikethrough)

        menu.add_separator()

        # Highlight colors (flat, no submenu)
        for color in self.HIGHLIGHT_NAMES:
            menu.add_command(
                label=self.tr(f"hl_{color}"),
                command=lambda c=color: self.apply_highlight(c))
        has_hl = any(self.text_area.tag_nextrange(f"highlight_{c}", tk.SEL_FIRST, tk.SEL_LAST)
                     for c in self.HIGHLIGHT_NAMES)
        if has_hl:
            menu.add_command(label=self.tr("remove_highlight"), command=self.remove_highlight)

        menu.add_separator()
        menu.add_command(label=self.tr("save_as_nb"), command=self.save_selection_as_notebook)
        menu.add_command(label=self.tr("copy_nb_link"), command=self.copy_notebook_link)

        menu.tk_popup(event.x_root, event.y_root)

    def copy_notebook_link(self):
        """Copy current notebook's [[link]] to clipboard"""
        link_text = f"[[{self.current_notebook}]]"
        self.root.clipboard_clear()
        self.root.clipboard_append(link_text)

    def _save_highlight_snapshot(self, first_line, last_line):
        """Save a lightweight snapshot of highlight tags for the given line range."""
        ta = self.text_area
        snapshot = {}  # {color: [(start, end), ...]}
        for c in self.HIGHLIGHT_NAMES:
            ranges = []
            raw = ta.tag_ranges(f"highlight_{c}")
            for i in range(0, len(raw), 2):
                s, e = str(raw[i]), str(raw[i + 1])
                s_line = int(s.split('.')[0])
                e_line = int(e.split('.')[0])
                # Include if overlaps with our line range
                if e_line >= first_line and s_line <= last_line:
                    ranges.append((s, e))
            if ranges:
                snapshot[c] = ranges
        return snapshot

    def _restore_highlight_snapshot(self, snapshot, first_line, last_line):
        """Restore highlight tags from a snapshot for the given line range."""
        ta = self.text_area
        # Remove all highlights in range
        for c in self.HIGHLIGHT_NAMES:
            ta.tag_remove(f"highlight_{c}", f"{first_line}.0", f"{last_line}.end")
        # Re-apply from snapshot
        for c, ranges in snapshot.items():
            for s, e in ranges:
                ta.tag_add(f"highlight_{c}", s, e)
        ta.tag_raise("md_elide")
        self._schedule_markdown_update()

    def _do_highlight_with_undo(self, first_line, last_line, apply_fn):
        """Execute a highlight operation with lightweight undo support."""
        ta = self.text_area
        before = self._save_highlight_snapshot(first_line, last_line)
        cursor_pos = ta.index(tk.INSERT)

        apply_fn()

        after = self._save_highlight_snapshot(first_line, last_line)
        fl, ll = first_line, last_line

        # Push lightweight undo (no edit_reset, no full content rebuild)
        def undo_op():
            self._restore_highlight_snapshot(before, fl, ll)
            try:
                ta.mark_set(tk.INSERT, cursor_pos)
            except:
                pass
        def redo_op():
            self._restore_highlight_snapshot(after, fl, ll)
            try:
                ta.mark_set(tk.INSERT, cursor_pos)
            except:
                pass

        self.undo_stack.append(("highlight", undo_op, redo_op))
        self.redo_stack.clear()
        self.content_modified = True
        self.schedule_auto_save()
        self._schedule_markdown_update()

    def apply_highlight(self, color):
        """Apply highlight background to selected text, skipping empty lines"""
        ta = self.text_area
        if not ta.tag_ranges(tk.SEL):
            return
        first_line = int(ta.index(tk.SEL_FIRST).split('.')[0])
        last_line = int(ta.index(tk.SEL_LAST).split('.')[0])

        def apply_fn():
            for c in self.HIGHLIGHT_NAMES:
                ta.tag_remove(f"highlight_{c}", f"{first_line}.0", f"{last_line}.end")
            for ln in range(first_line, last_line + 1):
                if ta.get(f"{ln}.0", f"{ln}.end").strip():
                    ta.tag_add(f"highlight_{color}", f"{ln}.0", f"{ln}.end")
            ta.tag_raise("md_elide")

        self._do_highlight_with_undo(first_line, last_line, apply_fn)

    def remove_highlight(self):
        """Remove all highlight tags from selected text"""
        ta = self.text_area
        if not ta.tag_ranges(tk.SEL):
            return
        first_line = int(ta.index(tk.SEL_FIRST).split('.')[0])
        last_line = int(ta.index(tk.SEL_LAST).split('.')[0])

        def apply_fn():
            for c in self.HIGHLIGHT_NAMES:
                ta.tag_remove(f"highlight_{c}", tk.SEL_FIRST, tk.SEL_LAST)

        self._do_highlight_with_undo(first_line, last_line, apply_fn)

    def _toggle_line_highlight(self, color, event=None):
        """Toggle highlight on cursor line or selected lines (Cmd+1~5).
        Skips empty lines (no visible content)."""
        ta = self.text_area
        hl_tag = f"highlight_{color}"
        # Determine line range
        if ta.tag_ranges(tk.SEL):
            first_line = int(ta.index(tk.SEL_FIRST).split('.')[0])
            last_line = int(ta.index(tk.SEL_LAST).split('.')[0])
        else:
            first_line = int(ta.index(tk.INSERT).split('.')[0])
            last_line = first_line

        # Check if ALL non-empty lines already have this color → toggle off
        all_have = True
        for ln in range(first_line, last_line + 1):
            if ta.get(f"{ln}.0", f"{ln}.end").strip():
                if not ta.tag_nextrange(hl_tag, f"{ln}.0", f"{ln}.end"):
                    all_have = False
                    break

        def apply_fn():
            for ln in range(first_line, last_line + 1):
                line_text = ta.get(f"{ln}.0", f"{ln}.end")
                ls, le = f"{ln}.0", f"{ln}.end"
                for c in self.HIGHLIGHT_NAMES:
                    ta.tag_remove(f"highlight_{c}", ls, le)
                if not all_have and line_text.strip():
                    ta.tag_add(hl_tag, ls, le)
            ta.tag_raise("md_elide")

        self._do_highlight_with_undo(first_line, last_line, apply_fn)
        return "break"

    def _toggle_line_highlight_remove(self, line_num):
        """Remove all highlights from a specific line."""
        ta = self.text_area
        ln = int(line_num)
        def apply_fn():
            for c in self.HIGHLIGHT_NAMES:
                ta.tag_remove(f"highlight_{c}", f"{ln}.0", f"{ln}.end")
        self._do_highlight_with_undo(ln, ln, apply_fn)

    def apply_strikethrough(self):
        """Apply strikethrough tag to selected text"""
        if self.text_area.tag_ranges(tk.SEL):
            self.save_undo_state()
            self.text_area.tag_add("strikethrough", tk.SEL_FIRST, tk.SEL_LAST)
            self.content_modified = True
            self.schedule_auto_save()

    def remove_strikethrough(self):
        """Remove strikethrough tag from selected text"""
        if self.text_area.tag_ranges(tk.SEL):
            self.save_undo_state()
            self.text_area.tag_remove("strikethrough", tk.SEL_FIRST, tk.SEL_LAST)
            self.content_modified = True
            self.schedule_auto_save()

    # ── Save Selection as Notebook ─────────────────────────────────────

    def _get_selected_content_with_markers(self):
        """Get selected text content with image/file/strikethrough/highlight markers"""
        ta = self.text_area
        sel = ta.tag_ranges(tk.SEL)
        if not sel:
            return ""
        sel_start, sel_end = str(sel[0]), str(sel[1])

        def _idx(s):
            line, col = s.split(".")
            return (int(line), int(col))

        sel_s, sel_e = _idx(sel_start), _idx(sel_end)
        dump_data = ta.dump(sel_start, sel_end, text=True, image=True)

        # Build skip ranges and file markers (same logic as get_content_with_markers)
        skip_ranges = []
        file_markers = {}
        skip_range_ends = {}
        for tag in ta.tag_names():
            if tag.startswith("icon_"):
                internal_filename = tag[5:]
                ranges = ta.tag_ranges(tag)
                if ranges:
                    icon_start = str(ranges[0])
                    file_tag = f"file_{internal_filename}"
                    file_ranges = ta.tag_ranges(file_tag)
                    if file_ranges:
                        file_end = str(file_ranges[1])
                        s, e = _idx(icon_start), _idx(file_end)
                        skip_ranges.append((s, e))
                        file_markers[s] = f"[FILE:{internal_filename}]"
                        skip_range_ends[s] = e
            elif tag.startswith("imgname_"):
                internal_filename = tag[8:]
                ranges = ta.tag_ranges(tag)
                if ranges:
                    name_start = str(ranges[0])
                    name_end = str(ranges[1])
                    prev_idx = ta.index(f"{name_start}-1c")
                    if ta.get(prev_idx) == "\n":
                        name_start = prev_idx
                    skip_ranges.append((_idx(name_start), _idx(name_end)))
            elif tag.startswith("url_preview_"):
                ranges = ta.tag_ranges(tag)
                for ri in range(0, len(ranges), 2):
                    s = _idx(str(ranges[ri]))
                    e = _idx(str(ranges[ri + 1]))
                    skip_ranges.append((s, e))
        skip_ranges.sort()

        # Strikethrough boundaries
        strike_starts = set()
        strike_ends = set()
        strike_raw = ta.tag_ranges("strikethrough")
        for si in range(0, len(strike_raw), 2):
            strike_starts.add(_idx(str(strike_raw[si])))
            strike_ends.add(_idx(str(strike_raw[si + 1])))

        # Highlight boundaries
        hl_starts = {}
        hl_ends = {}
        for color in self.HIGHLIGHT_NAMES:
            raw = ta.tag_ranges(f"highlight_{color}")
            for hi in range(0, len(raw), 2):
                hl_starts[_idx(str(raw[hi]))] = color
                hl_ends[_idx(str(raw[hi + 1]))] = color

        def is_in_skip_range(t):
            for s, e in skip_ranges:
                if s <= t < e:
                    return True
                if s > t:
                    break
            return False

        result = []
        strike_emitted_starts = set()
        strike_emitted_ends = set()
        hl_emitted_starts = set()
        hl_emitted_ends = set()
        i = 0
        while i < len(dump_data):
            key, value, index = dump_data[i]
            t = _idx(index)
            marker = file_markers.get(t)
            if marker:
                result.append(marker)
                end_t = skip_range_ends[t]
                i += 1
                while i < len(dump_data):
                    if _idx(dump_data[i][2]) >= end_t:
                        break
                    i += 1
                continue
            if is_in_skip_range(t):
                i += 1
                continue
            if t in strike_ends and t not in strike_emitted_ends:
                result.append('[/STRIKE]')
                strike_emitted_ends.add(t)
            if t in strike_starts and t not in strike_emitted_starts:
                result.append('[STRIKE]')
                strike_emitted_starts.add(t)
            if t in hl_ends and t not in hl_emitted_ends:
                result.append('[/HL]')
                hl_emitted_ends.add(t)
            if t in hl_starts and t not in hl_emitted_starts:
                result.append(f'[HL:{hl_starts[t]}]')
                hl_emitted_starts.add(t)
            if key == 'text':
                result.append(value)
            elif key == 'image':
                if value.startswith("img_"):
                    filename = value[4:]
                    # Strip duplicate suffix (e.g. "photo.png#2" → "photo.png")
                    if '#' in filename:
                        filename = filename[:filename.index('#')]
                    if filename in self.image_widths:
                        width = self.image_widths[filename]
                        result.append(f"[IMAGE:{filename}:{width}]")
                    else:
                        result.append(f"[IMAGE:{filename}]")
            i += 1

        for pos in sorted(strike_ends - strike_emitted_ends):
            if sel_s <= pos <= sel_e:
                result.append('[/STRIKE]')
        for pos in sorted(set(hl_ends) - hl_emitted_ends):
            if sel_s <= pos <= sel_e:
                result.append('[/HL]')

        content = "".join(result)
        if content.endswith("\n"):
            content = content[:-1]
        return content

    def _get_referenced_attachments(self, content):
        """Extract image and file filenames referenced in content markers"""
        filenames = set()
        for m in re.finditer(r'\[IMAGE:([^:\]]+)(?::\d+)?\]', content):
            filenames.add(m.group(1))
        for m in re.finditer(r'\[FILE:([^\]]+)\]', content):
            filenames.add(m.group(1))
        return filenames

    def save_selection_as_notebook(self):
        """Save selected text as a new notebook, replace selection with heading + link"""
        ta = self.text_area
        if not ta.tag_ranges(tk.SEL):
            return

        # Get selected content with markers before showing dialog
        selected_content = self._get_selected_content_with_markers()
        if not selected_content.strip():
            return

        t = self.current_theme_colors
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr("save_as_nb_title"))
        dialog.geometry("300x120")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=t["bg"])

        tk.Label(dialog, text=self.tr("nb_name_label"), bg=t["bg"], fg=t["fg"],
                 font=(SYSTEM_FONT, self.ui_font_size)).pack(pady=(10, 5))
        entry = ttk.Entry(dialog, width=30, style="Sidebar.TEntry")
        entry.pack(pady=5, padx=20)
        entry.focus_set()

        def do_save():
            name = entry.get().strip()
            if not name:
                return
            if name in self.get_notebooks_list():
                import tkinter.messagebox as messagebox
                messagebox.showwarning(self.tr("warning"), self.tr("nb_exists"), parent=dialog)
                return

            # Create notebook directory
            notebook_path = os.path.join(self.notebooks_dir, name)
            os.makedirs(notebook_path)
            os.makedirs(os.path.join(notebook_path, self.attachments_dir))

            # Copy referenced attachments to new notebook
            referenced = self._get_referenced_attachments(selected_content)
            src_attach = self.get_attachments_path()
            dst_attach = os.path.join(notebook_path, self.attachments_dir)
            for fname in referenced:
                src = os.path.join(src_attach, fname)
                if os.path.exists(src):
                    import shutil
                    shutil.copy2(src, os.path.join(dst_attach, fname))

            # Save content to new notebook's notes file
            note_path = os.path.join(notebook_path, self.note_file)
            with open(note_path, "w", encoding="utf-8") as f:
                f.write(selected_content)

            dialog.destroy()

            # Replace selection with heading + notebook link
            self.save_undo_state()
            # Check if selection starts at beginning of line
            sel_start = ta.index(tk.SEL_FIRST)
            sel_end = ta.index(tk.SEL_LAST)
            line_start_col = int(sel_start.split(".")[1])
            prefix = "\n" if line_start_col != 0 else ""
            replacement = f"{prefix}### {name}\n[[{name}]]\n"
            ta.delete(sel_start, sel_end)
            ta.insert(sel_start, replacement)

            self.content_modified = True
            self.schedule_auto_save()

            # Update notebook list
            self.update_notebook_menu()
            self.refresh_notebook_listbox(self.notebook_search_var.get())

            # Re-apply markdown to render the link
            self._schedule_markdown_update()

        entry.bind("<Return>", lambda e: do_save())
        ttk.Button(dialog, text=self.tr("create"), command=do_save,
                   style="Toolbar.TButton").pack(pady=10)

    # ── Markdown Rendering ──────────────────────────────────────────────

    @staticmethod
    def _blend_color(color1, color2, ratio):
        """Blend two hex colors. ratio=0 → color1, ratio=1 → color2."""
        r1, g1, b1 = int(color1[1:3], 16), int(color1[3:5], 16), int(color1[5:7], 16)
        r2, g2, b2 = int(color2[1:3], 16), int(color2[3:5], 16), int(color2[5:7], 16)
        r = int(r1 + (r2 - r1) * ratio)
        g = int(g1 + (g2 - g1) * ratio)
        b = int(b1 + (b2 - b1) * ratio)
        return f"#{r:02x}{g:02x}{b:02x}"

    def setup_markdown_tags(self):
        """Create all md_ tags on the text widget."""
        t = self.current_theme_colors
        sz = self.current_font_size
        dim = t["fg_dim"]
        fg = t["fg"]
        accent = t["accent"]
        code_bg = self._blend_color(t["text_bg"], t["fg"], 0.07)

        ta = self.text_area
        # Headings
        for level, scale in ((1, 1.6), (2, 1.35), (3, 1.15)):
            hsz = int(sz * scale)
            ta.tag_configure(f"md_h{level}_marker", foreground=dim,
                             font=(SYSTEM_FONT, hsz, "bold"))
            ta.tag_configure(f"md_h{level}_text", foreground=fg,
                             font=(SYSTEM_FONT, hsz, "bold"))
        # Bold
        ta.tag_configure("md_bold_marker", foreground=dim,
                         font=(SYSTEM_FONT, sz, "bold"))
        ta.tag_configure("md_bold_text", foreground=fg,
                         font=(SYSTEM_FONT, sz, "bold"))
        # Italic
        ta.tag_configure("md_italic_marker", foreground=dim,
                         font=(SYSTEM_FONT, sz, "italic"))
        ta.tag_configure("md_italic_text", foreground=fg,
                         font=(SYSTEM_FONT, sz, "italic"))
        # Inline code
        ta.tag_configure("md_code_marker", foreground=dim,
                         font=(MONO_FONT, sz))
        ta.tag_configure("md_code_text", foreground=fg,
                         font=(MONO_FONT, sz), background=code_bg)
        # Code block
        ta.tag_configure("md_codeblock", foreground=fg,
                         font=(MONO_FONT, sz), background=code_bg)
        ta.tag_configure("md_codeblock_fence", foreground=dim,
                         font=(MONO_FONT, sz), background=code_bg)
        # Block quote
        ta.tag_configure("md_blockquote_marker", foreground=accent,
                         font=(SYSTEM_FONT, sz))
        ta.tag_configure("md_blockquote_text", foreground=fg,
                         font=(SYSTEM_FONT, sz, "italic"))
        # List marker
        ta.tag_configure("md_list_marker", foreground=accent,
                         font=(SYSTEM_FONT, sz))
        # Horizontal rule
        ta.tag_configure("md_hr", foreground=t["border"],
                         font=(SYSTEM_FONT, sz))
        # Elide tag for hiding markers on non-active lines
        ta.tag_configure("md_elide", elide=True)
        # URL title preview tag (dimmed text after URL)
        ta.tag_configure("url_preview", foreground=dim,
                         font=(SYSTEM_FONT, sz))

        # Bind cursor movement to show/hide markers on active line
        ta.bind("<ButtonRelease-1>", self._on_cursor_move, add="+")
        ta.bind("<KeyRelease>", self._on_cursor_move, add="+")

    def _update_markdown_tag_styles(self):
        """Re-configure md_ tag fonts/colors after theme or font-size change."""
        t = self.current_theme_colors
        sz = self.current_font_size
        dim = t["fg_dim"]
        fg = t["fg"]
        accent = t["accent"]
        code_bg = self._blend_color(t["text_bg"], t["fg"], 0.07)

        ta = self.text_area
        for level, scale in ((1, 1.6), (2, 1.35), (3, 1.15)):
            hsz = int(sz * scale)
            ta.tag_configure(f"md_h{level}_marker", foreground=dim,
                             font=(SYSTEM_FONT, hsz, "bold"))
            ta.tag_configure(f"md_h{level}_text", foreground=fg,
                             font=(SYSTEM_FONT, hsz, "bold"))
        ta.tag_configure("md_bold_marker", foreground=dim,
                         font=(SYSTEM_FONT, sz, "bold"))
        ta.tag_configure("md_bold_text", foreground=fg,
                         font=(SYSTEM_FONT, sz, "bold"))
        ta.tag_configure("md_italic_marker", foreground=dim,
                         font=(SYSTEM_FONT, sz, "italic"))
        ta.tag_configure("md_italic_text", foreground=fg,
                         font=(SYSTEM_FONT, sz, "italic"))
        ta.tag_configure("md_code_marker", foreground=dim,
                         font=(MONO_FONT, sz))
        ta.tag_configure("md_code_text", foreground=fg,
                         font=(MONO_FONT, sz), background=code_bg)
        ta.tag_configure("md_codeblock", foreground=fg,
                         font=(MONO_FONT, sz), background=code_bg)
        ta.tag_configure("md_codeblock_fence", foreground=dim,
                         font=(MONO_FONT, sz), background=code_bg)
        ta.tag_configure("md_blockquote_marker", foreground=accent,
                         font=(SYSTEM_FONT, sz))
        ta.tag_configure("md_blockquote_text", foreground=fg,
                         font=(SYSTEM_FONT, sz, "italic"))
        ta.tag_configure("md_list_marker", foreground=accent,
                         font=(SYSTEM_FONT, sz))
        ta.tag_configure("md_hr", foreground=t["border"],
                         font=(SYSTEM_FONT, sz))
        ta.tag_configure("md_elide", elide=True)
        # URL preview tag update
        ta.tag_configure("url_preview", foreground=dim,
                         font=(SYSTEM_FONT, sz))

    def _get_protected_ranges(self):
        """Return dict of {line_str: [(start, end), ...]} for file/icon/imgname/url_preview tags.
        Multi-line ranges (e.g. url_preview that spans newline + title) are
        registered under every line they touch so the per-line lookup in
        _is_in_protected catches indices on any of those lines."""
        ta = self.text_area
        protected = {}
        for tag in ta.tag_names():
            if tag.startswith(("file_", "icon_", "imgname_", "url_preview_")):
                ranges = ta.tag_ranges(tag)
                for i in range(0, len(ranges), 2):
                    s = str(ranges[i])
                    e = str(ranges[i + 1])
                    start_line = int(s.split('.')[0])
                    end_line = int(e.split('.')[0])
                    for ln in range(start_line, end_line + 1):
                        protected.setdefault(str(ln), []).append((s, e))
        return protected

    def _is_in_protected(self, idx, protected):
        """Check if a text index falls inside any protected range (line-based lookup)."""
        line = idx.split('.')[0]
        if line not in protected:
            return False
        ta = self.text_area
        for s, e in protected[line]:
            if ta.compare(idx, ">=", s) and ta.compare(idx, "<", e):
                return True
        return False

    def _record_elide(self, line_num, start, end):
        """Record a marker range to be elided and apply md_elide."""
        self._md_marker_ranges.setdefault(line_num, []).append((start, end))
        self.text_area.tag_add("md_elide", start, end)

    def apply_markdown_formatting(self):
        """Apply markdown styling tags to the entire text content."""
        ta = self.text_area

        # Remove URL previews first (they are ephemeral text, not part of saved content)
        self._remove_all_url_previews()

        # Clear and re-detect URL tags
        for tag in list(self.url_tags):
            ta.tag_delete(tag)
        self.url_tags.clear()

        # Clear and re-detect notebook link tags
        for tag in list(ta.tag_names()):
            if tag.startswith("nb_link_"):
                ta.tag_delete(tag)

        # Remove all existing md_ tags (including md_elide)
        for tag in ta.tag_names():
            if tag.startswith("md_"):
                ta.tag_remove(tag, "1.0", tk.END)
        # Ensure md_elide is always configured (may have been tag_delete'd by switch_notebook)
        ta.tag_configure("md_elide", elide=True)

        self._md_marker_ranges = {}

        content = ta.get("1.0", tk.END)
        if not content.strip():
            return

        protected = self._get_protected_ranges()

        # Detect and tag URLs in the content, collect for preview insertion
        _url_tag_pairs = []  # [(url, tag_name), ...] for deferred preview insertion
        for m in self.url_pattern.finditer(content):
            url = m.group(1)
            # Convert string offset to tk line.col index
            before = content[:m.start()]
            line_num = before.count('\n') + 1
            col = m.start() - before.rfind('\n') - 1
            url_start = f"{line_num}.{col}"
            url_end = f"{line_num}.{col + len(url)}"
            if not self._is_in_protected(url_start, protected):
                tag_name = self.create_url_tag(url, url_start, url_end)
                if url in self._url_title_cache:
                    _url_tag_pairs.append((url, tag_name))
        lines = content.split('\n')
        in_code_block = False

        for i, line in enumerate(lines):
            line_num = i + 1  # tk lines are 1-based
            line_start = f"{line_num}.0"
            line_end = f"{line_num}.{len(line)}"

            # Code block fence
            stripped = line.lstrip()
            if stripped.startswith("```"):
                indent = len(line) - len(stripped)
                fence_start = f"{line_num}.{indent}"
                if not self._is_in_protected(fence_start, protected):
                    ta.tag_add("md_codeblock_fence", line_start, line_end)
                    self._record_elide(line_num, line_start, line_end)
                in_code_block = not in_code_block
                continue

            # Inside code block
            if in_code_block:
                if not self._is_in_protected(line_start, protected):
                    ta.tag_add("md_codeblock", line_start, line_end)
                continue

            # Horizontal rule: --- or ___ or *** (3+ chars, optional spaces)
            if re.match(r'^[ ]{0,3}([-*_])\s*\1\s*\1[\s\1]*$', line) and len(line.strip()) >= 3:
                if not self._is_in_protected(line_start, protected):
                    ta.tag_add("md_hr", line_start, line_end)
                continue

            # Headings: # ## ###
            h_match = re.match(r'^(#{1,3})\s+(.+)', line)
            if h_match:
                marker = h_match.group(1)
                level = len(marker)
                text_start_col = h_match.start(2)
                m_start = f"{line_num}.0"
                m_end = f"{line_num}.{text_start_col}"  # include space after #
                t_start = f"{line_num}.{text_start_col}"
                t_end = line_end
                if not self._is_in_protected(m_start, protected):
                    ta.tag_add(f"md_h{level}_marker", m_start, m_end)
                    ta.tag_add(f"md_h{level}_text", t_start, t_end)
                    self._record_elide(line_num, m_start, m_end)
                continue  # Skip inline processing for heading lines

            # Block quote: > text
            bq_match = re.match(r'^(>)\s?(.*)', line)
            if bq_match:
                marker_end = 1
                text_start = bq_match.start(2)
                if not self._is_in_protected(line_start, protected):
                    ta.tag_add("md_blockquote_marker", line_start,
                               f"{line_num}.{marker_end}")
                    if bq_match.group(2):
                        ta.tag_add("md_blockquote_text",
                                   f"{line_num}.{text_start}", line_end)
                # Still process inline markdown within blockquote text
                self._apply_inline_markdown(line, line_num, protected)
                continue

            # List markers: - , * , 1. , 2.  (space after marker optional before non-ASCII)
            list_match = re.match(r'^(\s*)([-*]|\d+\.)(?:\s|(?=[^\x00-\x7F]))', line)
            if list_match:
                indent = len(list_match.group(1))
                marker = list_match.group(2)
                marker_start = f"{line_num}.{indent}"
                marker_end = f"{line_num}.{indent + len(marker)}"
                if not self._is_in_protected(marker_start, protected):
                    ta.tag_add("md_list_marker", marker_start, marker_end)
                # Process inline markdown in list items
                self._apply_inline_markdown(line, line_num, protected)
                continue

            # Regular line — process inline markdown
            self._apply_inline_markdown(line, line_num, protected)

        # Ensure md_ tags have lower priority than strikethrough/url/file tags
        for tag in ta.tag_names():
            if tag.startswith("md_"):
                ta.tag_lower(tag)
        # Selection must render ABOVE highlight_ backgrounds, otherwise dragging
        # a selection across highlighted text makes the highlight color fight the
        # selection color and the region appears to flicker while selecting.
        # Order (low→high): md_* < highlight_* < sel < md_elide.
        try:
            ta.tag_raise("sel")
        except Exception:
            pass
        # md_elide must be the HIGHEST priority tag overall so elide always works
        # (highlight_ tags could otherwise override elide=True)
        ta.tag_raise("md_elide")

        # Un-elide markers on the current cursor line
        try:
            current_line = int(ta.index(tk.INSERT).split('.')[0])
            self._md_active_line = current_line
            if current_line in self._md_marker_ranges:
                for s, e in self._md_marker_ranges[current_line]:
                    ta.tag_remove("md_elide", s, e)
        except:
            pass

        # Update outline panel
        if hasattr(self, 'outline_text'):
            self._update_outline()

        # Insert cached URL title previews (reverse order to avoid index shift)
        for url, tag_name in reversed(_url_tag_pairs):
            self._insert_url_preview(url, self._url_title_cache[url], tag_name)

    def _apply_inline_markdown(self, line, line_num, protected):
        """Apply inline markdown (bold, italic, code) to a single line."""
        ta = self.text_area

        # Track regions covered by inline code to avoid * matching inside them
        code_regions = []

        # Inline code: `code`
        for m in re.finditer(r'(?<!`)`(?!`)(.+?)(?<!`)`(?!`)', line):
            ms = f"{line_num}.{m.start()}"
            me = f"{line_num}.{m.start() + 1}"
            ts = f"{line_num}.{m.start() + 1}"
            te = f"{line_num}.{m.end() - 1}"
            me2 = f"{line_num}.{m.end()}"
            ms2 = f"{line_num}.{m.end() - 1}"
            if self._is_in_protected(ms, protected):
                continue
            ta.tag_add("md_code_marker", ms, me)    # opening `
            ta.tag_add("md_code_text", ts, te)       # code content
            ta.tag_add("md_code_marker", ms2, me2)   # closing `
            self._record_elide(line_num, ms, me)     # elide opening `
            self._record_elide(line_num, ms2, me2)   # elide closing `
            code_regions.append((m.start(), m.end()))

        # Bold: **text**
        for m in re.finditer(r'\*\*(.+?)\*\*', line):
            if any(m.start() < ce and m.end() > cs for cs, ce in code_regions):
                continue
            ms = f"{line_num}.{m.start()}"
            me = f"{line_num}.{m.start() + 2}"
            ts = f"{line_num}.{m.start() + 2}"
            te = f"{line_num}.{m.end() - 2}"
            ms2 = f"{line_num}.{m.end() - 2}"
            me2 = f"{line_num}.{m.end()}"
            if self._is_in_protected(ms, protected):
                continue
            ta.tag_add("md_bold_marker", ms, me)     # opening **
            ta.tag_add("md_bold_text", ts, te)        # bold text
            ta.tag_add("md_bold_marker", ms2, me2)   # closing **
            self._record_elide(line_num, ms, me)     # elide opening **
            self._record_elide(line_num, ms2, me2)   # elide closing **

        # Italic: *text* (but not ** which is bold)
        for m in re.finditer(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', line):
            if any(m.start() < ce and m.end() > cs for cs, ce in code_regions):
                continue
            ms = f"{line_num}.{m.start()}"
            me = f"{line_num}.{m.start() + 1}"
            ts = f"{line_num}.{m.start() + 1}"
            te = f"{line_num}.{m.end() - 1}"
            ms2 = f"{line_num}.{m.end() - 1}"
            me2 = f"{line_num}.{m.end()}"
            if self._is_in_protected(ms, protected):
                continue
            ta.tag_add("md_italic_marker", ms, me)    # opening *
            ta.tag_add("md_italic_text", ts, te)       # italic text
            ta.tag_add("md_italic_marker", ms2, me2)  # closing *
            self._record_elide(line_num, ms, me)      # elide opening *
            self._record_elide(line_num, ms2, me2)    # elide closing *

        # Notebook links: [[notebook_name]]
        for m in re.finditer(r'\[\[([^\]]+)\]\]', line):
            if any(m.start() < ce and m.end() > cs for cs, ce in code_regions):
                continue
            full_start = f"{line_num}.{m.start()}"
            if self._is_in_protected(full_start, protected):
                continue
            nb_name = m.group(1)
            # Elide the [[ and ]] markers
            open_s = f"{line_num}.{m.start()}"
            open_e = f"{line_num}.{m.start() + 2}"
            close_s = f"{line_num}.{m.end() - 2}"
            close_e = f"{line_num}.{m.end()}"
            self._record_elide(line_num, open_s, open_e)
            self._record_elide(line_num, close_s, close_e)
            # Tag the visible name as a clickable notebook link
            name_s = f"{line_num}.{m.start() + 2}"
            name_e = f"{line_num}.{m.end() - 2}"
            tag_name = f"nb_link_{len(ta.tag_names())}"
            t = self.current_theme_colors
            ta.tag_add(tag_name, name_s, name_e)
            ta.tag_config(tag_name, foreground=t["accent_url"], underline=True)
            ta.tag_bind(tag_name, "<Button-1>", lambda e, n=nb_name: self._navigate_to_notebook(n))
            ta.tag_bind(tag_name, "<Enter>", lambda e, tn=tag_name: ta.config(cursor="hand2"))
            ta.tag_bind(tag_name, "<Leave>", lambda e: ta.config(cursor=""))
            # Also tag the markers for elide
            ta.tag_add("md_elide", open_s, open_e)
            ta.tag_add("md_elide", close_s, close_e)

    def _navigate_to_notebook(self, notebook_name):
        """Navigate to a notebook by name (from [[notebook_name]] link)"""
        notebooks = self.get_notebooks_list()
        if notebook_name in notebooks:
            self.switch_notebook(notebook_name)
        else:
            import tkinter.messagebox as messagebox
            messagebox.showwarning(self.tr("warning"),
                                   f"Notebook '{notebook_name}' not found.")

    def _on_cursor_move(self, event=None):
        """Show raw markers on the cursor line, hide them elsewhere."""
        try:
            line = int(self.text_area.index(tk.INSERT).split('.')[0])
        except Exception:
            return

        # Always update outline highlight (even on same line clicks)
        if hasattr(self, 'outline_text') and self._outline_visible:
            self._update_outline_active()

        # While a selection is active, don't show/hide markdown markers — toggling
        # elide reflows the text and makes the selection flicker/jump as it grows.
        if self.text_area.tag_ranges(tk.SEL):
            return

        if line == self._md_active_line:
            return
        old_line = self._md_active_line
        self._md_active_line = line
        ta = self.text_area
        # Re-elide markers on the previous line
        if old_line is not None and old_line in self._md_marker_ranges:
            for s, e in self._md_marker_ranges[old_line]:
                ta.tag_add("md_elide", s, e)
        # Un-elide markers on the new cursor line
        if line in self._md_marker_ranges:
            for s, e in self._md_marker_ranges[line]:
                ta.tag_remove("md_elide", s, e)

    def _schedule_markdown_update(self):
        """Schedule markdown re-render with 300ms debounce."""
        if self._md_update_timer_id is not None:
            self.root.after_cancel(self._md_update_timer_id)
        self._md_update_timer_id = self.root.after(300, self._do_markdown_update)

    def _do_markdown_update(self):
        """Execute the debounced markdown update."""
        self._md_update_timer_id = None
        try:
            self.apply_markdown_formatting()
        except Exception as e:
            print(f"Error in markdown formatting: {e}")
        # Refresh search highlights if search bar is open
        if self._search_visible and hasattr(self, '_search_var') and self._search_var.get():
            self._do_search()

    # ── In-Notebook Search (Cmd+F) ──────────────────────────────────────

    def _build_search_bar(self):
        """Create the search bar frame (initially hidden) above the text area."""
        t = self.current_theme_colors

        self._search_frame = tk.Frame(self.right_content, bg=t["bg_secondary"],
                                       highlightbackground=t["border"], highlightthickness=1)
        # Don't pack yet — shown/hidden by _toggle_search_bar

        inner = tk.Frame(self._search_frame, bg=t["bg_secondary"])
        inner.pack(fill=tk.X, padx=6, pady=4)

        # Search entry
        self._search_var = tk.StringVar()
        self._search_timer_id = None
        self._search_var.trace_add("write", lambda *_: self._schedule_search())
        self._search_entry = tk.Entry(
            inner, textvariable=self._search_var,
            font=(SYSTEM_FONT, self.ui_font_size),
            bg=t["entry_bg"], fg=t["entry_fg"],
            insertbackground=t["text_insert"],
            highlightthickness=1, highlightcolor=t["accent"],
            highlightbackground=t["border"], relief=tk.FLAT)
        self._search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Match count label
        self._search_count_label = tk.Label(
            inner, text="", font=(SYSTEM_FONT, self.ui_font_size - 1),
            bg=t["bg_secondary"], fg=t["fg_dim"], width=8)
        self._search_count_label.pack(side=tk.LEFT, padx=(6, 2))

        # Navigation buttons
        btn_font = (SYSTEM_FONT, self.ui_font_size)
        self._search_prev_btn = tk.Label(
            inner, text="▲", font=btn_font, cursor="hand2",
            bg=t["bg_secondary"], fg=t["fg_dim"])
        self._search_prev_btn.pack(side=tk.LEFT, padx=2)
        self._search_prev_btn.bind("<Button-1>", lambda e: self._search_prev())

        self._search_next_btn = tk.Label(
            inner, text="▼", font=btn_font, cursor="hand2",
            bg=t["bg_secondary"], fg=t["fg_dim"])
        self._search_next_btn.pack(side=tk.LEFT, padx=2)
        self._search_next_btn.bind("<Button-1>", lambda e: self._search_next())

        # Close button
        self._search_close_btn = tk.Label(
            inner, text="✕", font=(SYSTEM_FONT, self.ui_font_size), cursor="hand2",
            bg=t["bg_secondary"], fg=t["fg_dim"])
        self._search_close_btn.pack(side=tk.LEFT, padx=(2, 0))
        self._search_close_btn.bind("<Button-1>", lambda e: self._close_search_bar())

        # Key bindings on the entry
        self._search_entry.bind("<Return>", lambda e: self._search_next())
        self._search_entry.bind("<Shift-Return>", lambda e: self._search_prev())
        self._search_entry.bind("<Escape>", lambda e: self._close_search_bar())

        # Configure search highlight tags on text_area
        self.text_area.tag_configure("search_match",
                                      background=t["accent"] if self.current_theme == "dark" else "#b4d5fe",
                                      foreground="#ffffff" if self.current_theme == "dark" else "#1e1e2e")
        self.text_area.tag_configure("search_current",
                                      background="#f0a020",
                                      foreground="#1e1e2e")

    def _schedule_search(self):
        """Debounce search to avoid rapid Tcl calls on every keystroke."""
        if hasattr(self, '_search_timer_id') and self._search_timer_id is not None:
            self.root.after_cancel(self._search_timer_id)
        self._search_timer_id = self.root.after(150, self._do_search)

    def _toggle_search_bar(self):
        """Show or hide the search bar."""
        if not hasattr(self, '_search_frame'):
            self._build_search_bar()
        if self._search_visible:
            self._close_search_bar()
        else:
            self._show_search_bar()

    def _show_search_bar(self):
        """Display the search bar and focus the entry."""
        self._search_visible = True
        self._search_frame.pack(side=tk.TOP, fill=tk.X, before=self.text_container)
        # If there is selected text, populate the search entry with it
        try:
            sel = self.text_area.get(tk.SEL_FIRST, tk.SEL_LAST)
            if sel and "\n" not in sel and len(sel) < 200:
                self._search_var.set(sel)
        except tk.TclError:
            pass
        self._search_entry.focus_set()
        self._search_entry.select_range(0, tk.END)
        # Trigger initial search if entry has text
        if self._search_var.get():
            self._do_search()

    def _close_search_bar(self):
        """Hide the search bar and clear highlights."""
        if not hasattr(self, '_search_frame'):
            self._search_visible = False
            return
        self._search_visible = False
        if self._search_timer_id is not None:
            self.root.after_cancel(self._search_timer_id)
            self._search_timer_id = None
        self._search_frame.pack_forget()
        self.text_area.tag_remove("search_match", "1.0", tk.END)
        self.text_area.tag_remove("search_current", "1.0", tk.END)
        self._search_matches = []
        self._search_current_idx = -1
        self._search_count_label.configure(text="")
        self.text_area.focus_set()

    def _do_search(self):
        """Perform the search and highlight all matches (pure Python, minimal Tcl)."""
        self._search_timer_id = None
        ta = self.text_area
        ta.tag_remove("search_match", "1.0", tk.END)
        ta.tag_remove("search_current", "1.0", tk.END)
        self._search_matches = []
        self._search_current_idx = -1

        query = self._search_var.get()
        if not query:
            self._search_count_label.configure(text="")
            return

        # Get full text and search in pure Python (avoids repeated Tcl search calls)
        content = ta.get("1.0", "end-1c")
        query_lower = query.lower()
        content_lower = content.lower()
        qlen = len(query)

        # Find all match offsets in Python
        offsets = []
        start = 0
        while True:
            idx = content_lower.find(query_lower, start)
            if idx == -1:
                break
            offsets.append(idx)
            start = idx + max(1, qlen)

        if not offsets:
            self._search_count_label.configure(text="0/0")
            return

        # Convert string offsets to Tk line.col indices
        # Build a line-start offset table for O(1) conversion
        line_starts = [0]
        for i, ch in enumerate(content):
            if ch == '\n':
                line_starts.append(i + 1)

        def offset_to_index(off):
            # Binary search for the line
            lo, hi = 0, len(line_starts) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if line_starts[mid] <= off:
                    lo = mid
                else:
                    hi = mid - 1
            line = lo + 1  # Tk lines are 1-based
            col = off - line_starts[lo]
            return f"{line}.{col}"

        # Build match list and add tags in batch
        for off in offsets:
            s = offset_to_index(off)
            e = offset_to_index(off + qlen)
            self._search_matches.append((s, e))
            ta.tag_add("search_match", s, e)

        # Jump to match closest to cursor
        try:
            cursor_pos = ta.index(tk.INSERT)
        except tk.TclError:
            cursor_pos = "1.0"
        cursor_line, cursor_col = map(int, cursor_pos.split('.'))

        target_idx = 0
        for i, (s, _e) in enumerate(self._search_matches):
            sl, sc = map(int, s.split('.'))
            if (sl, sc) >= (cursor_line, cursor_col):
                target_idx = i
                break
        else:
            target_idx = 0

        self._search_current_idx = target_idx
        self._highlight_current_match()

    def _highlight_current_match(self):
        """Highlight the current match and scroll to it."""
        if not self._search_matches:
            return
        # Remove previous current highlight
        self.text_area.tag_remove("search_current", "1.0", tk.END)
        idx = self._search_current_idx
        start, end = self._search_matches[idx]
        self.text_area.tag_add("search_current", start, end)
        self.text_area.tag_raise("search_current")
        self.text_area.see(start)
        n = len(self._search_matches)
        self._search_count_label.configure(text=f"{idx + 1}/{n}")

    def _search_next(self):
        """Navigate to next search match."""
        if not self._search_matches:
            return
        self._search_current_idx = (self._search_current_idx + 1) % len(self._search_matches)
        self._highlight_current_match()

    def _search_prev(self):
        """Navigate to previous search match."""
        if not self._search_matches:
            return
        self._search_current_idx = (self._search_current_idx - 1) % len(self._search_matches)
        self._highlight_current_match()

    # ── Outline Panel (Table of Contents) ─────────────────────────────────

    def _build_outline_panel(self):
        """Create the floating outline panel over the text area."""
        t = self.current_theme_colors

        self.outline_frame = tk.Frame(self.text_container, bg=t["bg_secondary"],
                                      highlightbackground=t["border"], highlightthickness=1)

        # Bottom-edge drag handle for vertical resizing (pack first to reserve space)
        self._outline_bottom_handle = tk.Frame(self.outline_frame, height=5, bg=t["bg_secondary"],
                                               cursor="sb_v_double_arrow")
        self._outline_bottom_handle.pack(side=tk.BOTTOM, fill=tk.X)
        self._outline_bottom_handle.bind("<Button-1>", self._outline_vresize_start)
        self._outline_bottom_handle.bind("<B1-Motion>", self._outline_vresize_drag)
        self._outline_bottom_handle.bind("<ButtonRelease-1>", self._outline_resize_end)
        self._outline_bottom_handle.bind("<Enter>", lambda e: self._outline_bottom_handle.configure(bg=t["border"]))
        self._outline_bottom_handle.bind("<Leave>", lambda e: self._outline_bottom_handle.configure(bg=t["bg_secondary"]))

        # Left-edge drag handle for horizontal resizing
        self._outline_drag_handle = tk.Frame(self.outline_frame, width=5, bg=t["bg_secondary"],
                                             cursor="sb_h_double_arrow")
        self._outline_drag_handle.pack(side=tk.LEFT, fill=tk.Y)
        self._outline_drag_handle.bind("<Button-1>", self._outline_resize_start)
        self._outline_drag_handle.bind("<B1-Motion>", self._outline_resize_drag)
        self._outline_drag_handle.bind("<ButtonRelease-1>", self._outline_resize_end)
        self._outline_drag_handle.bind("<Enter>", lambda e: self._outline_drag_handle.configure(bg=t["border"]))
        self._outline_drag_handle.bind("<Leave>", lambda e: self._outline_drag_handle.configure(bg=t["bg_secondary"]))

        # Content frame (fills remaining space)
        outline_content = tk.Frame(self.outline_frame, bg=t["bg_secondary"])
        outline_content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Title bar
        title_bar = tk.Frame(outline_content, bg=t["bg_secondary"])
        title_bar.pack(fill=tk.X, padx=4, pady=(4, 0))

        self.outline_title = tk.Label(title_bar, text=self.tr("outline_title"), font=(SYSTEM_FONT, 11, "bold"),
                                      bg=t["bg_secondary"], fg=t["fg_dim"])
        self.outline_title.pack(side=tk.LEFT)

        self.outline_close_btn = tk.Label(title_bar, text="✕", font=(SYSTEM_FONT, 10),
                                          bg=t["bg_secondary"], fg=t["fg_dim"], cursor="hand2")
        self.outline_close_btn.pack(side=tk.RIGHT)
        self.outline_close_btn.bind("<Button-1>", lambda e: self._toggle_outline())

        # Text widget for heading items (supports per-line font via tags)
        self.outline_text = tk.Text(
            outline_content, font=(SYSTEM_FONT, 11),
            bg=t["bg_secondary"], fg=t["fg"],
            relief=tk.FLAT, highlightthickness=0, borderwidth=0,
            cursor="hand2", wrap=tk.NONE, padx=0, pady=2,
            state=tk.DISABLED, spacing1=4, spacing3=4)
        self.outline_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 4))

        # Tags for heading levels (font sizes derived from _outline_font_size)
        self._apply_outline_font_tags()

        # Hover highlight tag
        self.outline_text.tag_configure("ol_hover",
                                        background=t["bg_tertiary"])
        # Active heading (cursor is under this section)
        self.outline_text.tag_configure("ol_active",
                                        foreground=t["accent"])
        # Highlighted headings get a thin colored left bar instead of a full
        # background fill — see _update_outline.
        for color in self.HIGHLIGHT_NAMES:
            self.outline_text.tag_configure(f"ol_bar_{color}",
                                            foreground=t[f"hl_{color}"])
        # Placeholder bar (no highlight) — painted in the panel bg so it is
        # invisible but occupies the same width, keeping text aligned.
        self.outline_text.tag_configure("ol_bar_none",
                                        foreground=t["bg_secondary"])

        # Flash highlight tags
        self.text_area.tag_configure("outline_flash",
                                     background=t["list_select_bg"])
        self._outline_flash_timer = None

        self.outline_text.bind("<Button-1>", self._on_outline_click)
        self.outline_text.bind("<Motion>", self._on_outline_hover)
        self.outline_text.bind("<Leave>", self._on_outline_leave)
        self.outline_text.bind("<Button-2>", self._show_outline_context_menu)
        self.outline_text.bind("<Control-Button-1>", self._show_outline_context_menu)
        self.outline_text.bind("<MouseWheel>", self._on_outline_scroll)

        # Initially hidden
        self.outline_frame.place_forget()

    def _update_outline(self):
        """Extract headings from text and populate the outline panel."""
        content = self.text_area.get("1.0", tk.END)
        headings = []
        for i, line in enumerate(content.split('\n')):
            m = re.match(r'^(#{1,3})\s+(.+)', line)
            if m:
                headings.append((i + 1, len(m.group(1)), m.group(2).strip()))

        self._outline_headings = headings

        self.outline_text.configure(state=tk.NORMAL)
        self.outline_text.delete("1.0", tk.END)
        # Outline rebuilt — invalidate the active-index cache so the active
        # heading is re-tagged (see _highlight_outline_for_line's fast path).
        self._outline_last_active_idx = None
        t = self.THEMES[self.current_theme]
        indent = {1: "", 2: "  ", 3: "    "}
        # Estimate max chars that fit in panel (account for padding, drag handle)
        avail_px = self._outline_width - 30
        char_px = max(self._outline_font_size * 0.7, 6)
        max_chars = max(8, int(avail_px / char_px))
        for idx, (line_num, level, text) in enumerate(headings):
            if idx > 0:
                self.outline_text.insert(tk.END, "\n")
            tag = f"ol_h{level}"
            prefix = indent.get(level, "")
            # Check if this heading line has a highlight tag
            hl_color = None
            for color in self.HIGHLIGHT_NAMES:
                tag_name = f"highlight_{color}"
                ranges = self.text_area.tag_ranges(tag_name)
                for i in range(0, len(ranges), 2):
                    start_line = int(str(ranges[i]).split('.')[0])
                    end_line = int(str(ranges[i+1]).split('.')[0])
                    if start_line <= line_num <= end_line:
                        hl_color = color
                        break
                if hl_color:
                    break
            # Truncate to fit panel width
            indent_len = len(prefix)
            display_text = text if len(text) + indent_len <= max_chars else text[:max_chars - indent_len - 1] + "…"
            # col 0: leading padding space. col 1: thin colored left bar for
            # highlighted headings — a colored glyph instead of a full
            # background fill, so the outline keeps a clean right edge.
            self.outline_text.insert(tk.END, " ", tag)
            # Always render the bar glyph (same width on every row so text stays
            # aligned); colour it when highlighted, else make it invisible.
            bar_tag = f"ol_bar_{hl_color}" if hl_color else "ol_bar_none"
            self.outline_text.insert(tk.END, "▎", bar_tag)
            self.outline_text.insert(tk.END, prefix + display_text, tag)
        self.outline_text.configure(state=tk.DISABLED)

        # Auto-hide when no headings, show if toggled on and there are headings
        if not headings:
            self.outline_frame.place_forget()
        elif self._outline_visible and headings:
            self._show_outline()

    def _on_outline_click(self, event=None):
        """Handle click on an outline heading item."""
        idx = self.outline_text.index(f"@{event.x},{event.y}")
        ol_line = int(idx.split(".")[0]) - 1  # 0-based index into headings list
        if 0 <= ol_line < len(self._outline_headings):
            line_num = self._outline_headings[ol_line][0]
            target = f"{line_num}.0"
            self.text_area.mark_set(tk.INSERT, target)
            # Scroll target line to vertical center
            self.text_area.see(target)
            self.text_area.update_idletasks()
            dinfo = self.text_area.dlineinfo(target)
            if dinfo:
                widget_h = self.text_area.winfo_height()
                line_y = dinfo[1]
                line_h = dinfo[3]
                shift_px = line_y - (widget_h // 2) + (line_h // 2)
                if shift_px != 0 and line_h > 0:
                    # Convert pixel shift to line units
                    units = shift_px // line_h
                    if units != 0:
                        self.text_area.yview_scroll(units, "units")
            # Highlight clicked item in outline panel
            self.outline_text.configure(state=tk.NORMAL)
            self.outline_text.tag_remove("ol_active", "1.0", tk.END)
            level = self._outline_headings[ol_line][1]
            # Skip blank col 0 + bar slot (col 1) + indent.
            text_col = 2 + {1: 0, 2: 2, 3: 4}.get(level, 0)
            self.outline_text.tag_add("ol_active",
                                      f"{ol_line + 1}.{text_col}", f"{ol_line + 1}.end")
            self.outline_text.tag_raise("ol_active")
            self.outline_text.configure(state=tk.DISABLED)
            # Flash highlight the heading line in text_area (auto-clears after 1s)
            self._flash_heading_line(line_num)

    def _on_outline_hover(self, event):
        """Highlight heading under cursor."""
        self.outline_text.tag_remove("ol_hover", "1.0", tk.END)
        idx = self.outline_text.index(f"@{event.x},{event.y}")
        line = idx.split(".")[0]
        self.outline_text.tag_add("ol_hover", f"{line}.0", f"{line}.end")

    def _on_outline_leave(self, event):
        """Remove hover highlight."""
        self.outline_text.tag_remove("ol_hover", "1.0", tk.END)

    def _flash_heading_line(self, line_num):
        """Briefly highlight a heading line in text_area, auto-remove after 1s."""
        # Cancel previous flash timer
        if self._outline_flash_timer is not None:
            self.root.after_cancel(self._outline_flash_timer)
            self.text_area.tag_remove("outline_flash", "1.0", tk.END)
        self.text_area.tag_add("outline_flash", f"{line_num}.0", f"{line_num}.end")
        self.text_area.tag_raise("outline_flash")
        self._outline_flash_timer = self.root.after(
            1000, self._clear_outline_flash)

    def _clear_outline_flash(self):
        """Remove the flash highlight."""
        self._outline_flash_timer = None
        self.text_area.tag_remove("outline_flash", "1.0", tk.END)

    def _update_outline_active(self):
        """Highlight the outline heading corresponding to the cursor position."""
        if not self._outline_visible or not self._outline_headings:
            return
        try:
            cursor_line = int(self.text_area.index(tk.INSERT).split('.')[0])
        except Exception:
            return
        self._highlight_outline_for_line(cursor_line)

    def _update_outline_from_scroll(self):
        """Update outline highlight from scroll position (throttled).

        The scrollbar callback fires on every scroll tick; during a fast scroll
        or an auto-scrolling selection-drag that means dozens of calls/sec, each
        doing several edits + see() on the outline. Throttle to ~60ms with a
        trailing update so the outline stays in sync without stuttering the drag.
        """
        if not self._outline_visible or not self._outline_headings:
            return
        import time
        now = time.time() * 1000
        last = getattr(self, '_outline_scroll_last', 0)
        if now - last < 60:
            # Coalesce: ensure one trailing sync after the scroll burst settles
            if getattr(self, '_outline_scroll_pending', None) is None:
                self._outline_scroll_pending = self.root.after(
                    70, self._do_outline_scroll_sync)
            return
        self._do_outline_scroll_sync()

    def _do_outline_scroll_sync(self):
        self._outline_scroll_pending = None
        if not self._outline_visible or not self._outline_headings:
            return
        import time
        self._outline_scroll_last = time.time() * 1000
        try:
            # Use a point ~1/4 down the viewport so the outline highlights
            # the heading a bit earlier, before it scrolls off the top.
            offset_y = self.text_area.winfo_height() // 4
            visible_line = int(self.text_area.index(f"@0,{offset_y}").split('.')[0])
        except Exception:
            return
        self._highlight_outline_for_line(visible_line)

    def _highlight_outline_for_line(self, text_line):
        """Highlight the outline entry whose heading is at or before text_line."""
        active_idx = -1
        for i, (line_num, _, _) in enumerate(self._outline_headings):
            if line_num <= text_line:
                active_idx = i
            else:
                break

        # Nothing to do if the active heading hasn't changed — avoids the
        # ~2ms of edits+see() on every scroll tick within the same section.
        if active_idx == getattr(self, '_outline_last_active_idx', None):
            return
        self._outline_last_active_idx = active_idx

        self.outline_text.configure(state=tk.NORMAL)
        self.outline_text.tag_remove("ol_active", "1.0", tk.END)
        if active_idx >= 0:
            ol_line = active_idx + 1  # 1-based line in outline_text
            _, level, _ = self._outline_headings[active_idx]
            # Active section is shown by accent-coloured text alone. Skip the
            # blank col 0 + bar slot (col 1) + indent so the accent lands on the
            # heading text, not the left bar.
            text_col = 2 + {1: 0, 2: 2, 3: 4}.get(level, 0)
            self.outline_text.tag_add("ol_active", f"{ol_line}.{text_col}", f"{ol_line}.end")
            self.outline_text.tag_raise("ol_active")
            self.outline_text.see(f"{ol_line}.0")
        self.outline_text.configure(state=tk.DISABLED)

    def _on_outline_scroll(self, event):
        """Scroll the outline panel list itself."""
        if event.delta > 0:
            self.outline_text.yview_scroll(-3, "units")
        else:
            self.outline_text.yview_scroll(3, "units")
        return "break"

    def _toggle_outline(self):
        """Toggle outline panel visibility."""
        self._outline_visible = not self._outline_visible
        if self._outline_visible:
            self._update_outline()
            if self._outline_headings:
                self._show_outline()
        else:
            self.outline_frame.place_forget()

    def _show_outline(self):
        """Place the outline panel in the top-right of text_container."""
        n = len(self._outline_headings)
        if n == 0:
            return
        if self._outline_height > 0:
            height = self._outline_height
        else:
            # Auto-fit: per-heading line height + title bar + padding
            height = min(n * 30 + 40, 500)
        # Clamp to container height
        container_h = self.text_container.winfo_height()
        if container_h > 50:
            height = min(height, container_h - 10)
        self.outline_frame.place(relx=1.0, rely=0.0, anchor="ne",
                                 x=-25, y=5, width=self._outline_width, height=height)
        self.outline_frame.lift()

    def _outline_resize_start(self, event):
        """Record starting x for outline drag resize."""
        self._outline_drag_x = event.x_root
        self._outline_drag_w = self._outline_width

    def _outline_resize_drag(self, event):
        """Resize outline width by dragging the left edge."""
        dx = self._outline_drag_x - event.x_root
        new_w = max(150, min(self._outline_drag_w + dx, 500))
        self._outline_width = new_w
        self._show_outline()

    def _outline_vresize_start(self, event):
        """Record starting y for outline vertical drag resize."""
        self._outline_drag_y = event.y_root
        info = self.outline_frame.place_info()
        self._outline_drag_h = int(info.get("height", 0)) or self.outline_frame.winfo_height()

    def _outline_vresize_drag(self, event):
        """Resize outline height by dragging the bottom edge."""
        dy = event.y_root - self._outline_drag_y
        new_h = max(100, self._outline_drag_h + dy)
        container_h = self.text_container.winfo_height()
        if container_h > 50:
            new_h = min(new_h, container_h - 10)
        self._outline_height = new_h
        self._show_outline()

    def _outline_resize_end(self, event):
        """Persist outline size after drag ends."""
        self.save_config()

    def _apply_outline_font_tags(self):
        """Configure outline heading tags based on current _outline_font_size."""
        t = self.current_theme_colors
        sz = self._outline_font_size
        self.outline_text.configure(font=(SYSTEM_FONT, sz))
        self.outline_text.tag_configure("ol_h1", font=(SYSTEM_FONT, sz + 2, "bold"),
                                        foreground=t["fg"])
        self.outline_text.tag_configure("ol_h2", font=(SYSTEM_FONT, sz),
                                        foreground=t["fg"])
        self.outline_text.tag_configure("ol_h3", font=(SYSTEM_FONT, sz - 2),
                                        foreground=t["fg_dim"])

    def _show_outline_context_menu(self, event):
        """Show right-click context menu on outline panel."""
        menu = self.make_styled_menu()
        menu.add_command(label=self.tr("font_larger"), command=self._outline_font_increase)
        menu.add_command(label=self.tr("font_smaller"), command=self._outline_font_decrease)
        menu.add_separator()
        menu.add_command(label=self.tr("reset_size"), command=self._outline_reset_size)
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _outline_font_increase(self):
        """Increase outline font size."""
        self._outline_font_size = min(self._outline_font_size + 1, 24)
        self._apply_outline_font_tags()
        self.save_config()

    def _outline_font_decrease(self):
        """Decrease outline font size."""
        self._outline_font_size = max(self._outline_font_size - 1, 8)
        self._apply_outline_font_tags()
        self.save_config()

    def _outline_reset_size(self):
        """Reset outline panel to default size."""
        self._outline_font_size = 12
        self._outline_width = 240
        self._outline_height = 0
        self._apply_outline_font_tags()
        self._show_outline()
        self.save_config()

    def _serialize_range(self, start, end):
        """Serialize a text range to marker format (similar to get_content_with_markers
        but only for the given range). Used by rich-copy.
        Returns the serialized string, or empty string on failure.
        """
        try:
            def _idx(s):
                line, col = s.split(".")
                return (int(line), int(col))

            start_t = _idx(self.text_area.index(start))
            end_t = _idx(self.text_area.index(end))

            dump_data = self.text_area.dump(start, end, text=True, image=True)

            # Build skip ranges for file/image labels within the selection
            skip_ranges = []
            file_markers = {}
            skip_range_ends = {}
            for tag in self.text_area.tag_names():
                if tag.startswith("icon_"):
                    internal_filename = tag[5:]
                    ranges = self.text_area.tag_ranges(tag)
                    if ranges:
                        icon_start = str(ranges[0])
                        file_tag = f"file_{internal_filename}"
                        file_ranges = self.text_area.tag_ranges(file_tag)
                        if file_ranges:
                            file_end = str(file_ranges[1])
                            s = _idx(icon_start)
                            e = _idx(file_end)
                            if s >= start_t and s < end_t:
                                skip_ranges.append((s, e))
                                file_markers[s] = f"[FILE:{internal_filename}]"
                                skip_range_ends[s] = e
                elif tag.startswith("imgname_"):
                    ranges = self.text_area.tag_ranges(tag)
                    if ranges:
                        name_start = str(ranges[0])
                        name_end = str(ranges[1])
                        prev_idx = self.text_area.index(f"{name_start}-1c")
                        if self.text_area.get(prev_idx) == "\n":
                            name_start = prev_idx
                        s = _idx(name_start)
                        e = _idx(name_end)
                        if s >= start_t and s < end_t:
                            skip_ranges.append((s, e))
                elif tag.startswith("url_preview_"):
                    ranges = self.text_area.tag_ranges(tag)
                    for ri in range(0, len(ranges), 2):
                        s = _idx(str(ranges[ri]))
                        e = _idx(str(ranges[ri + 1]))
                        if s >= start_t and s < end_t:
                            skip_ranges.append((s, e))

            skip_ranges.sort()

            def is_in_skip_range(t):
                for s, e in skip_ranges:
                    if s <= t < e:
                        return True
                    if s > t:
                        break
                return False

            # Highlight and strikethrough within the selection
            strike_starts = set()
            strike_ends = set()
            strike_raw = self.text_area.tag_ranges("strikethrough")
            for si in range(0, len(strike_raw), 2):
                s = _idx(str(strike_raw[si]))
                e = _idx(str(strike_raw[si + 1]))
                if s < end_t and e > start_t:
                    strike_starts.add(max(s, start_t))
                    strike_ends.add(min(e, end_t))

            hl_starts = {}
            hl_ends = {}
            for color in self.HIGHLIGHT_NAMES:
                raw = self.text_area.tag_ranges(f"highlight_{color}")
                for hi in range(0, len(raw), 2):
                    s = _idx(str(raw[hi]))
                    e = _idx(str(raw[hi + 1]))
                    if s < end_t and e > start_t:
                        hl_starts[max(s, start_t)] = color
                        hl_ends[min(e, end_t)] = color

            result = []
            strike_open = False
            hl_open = None
            i = 0
            while i < len(dump_data):
                key, value, index = dump_data[i]
                t = _idx(index)

                marker = file_markers.get(t)
                if marker:
                    if strike_open:
                        result.append('[/STRIKE]'); strike_open = False
                    if hl_open:
                        result.append('[/HL]'); hl_open = None
                    result.append(marker)
                    end_t_marker = skip_range_ends.get(t)
                    i += 1
                    while i < len(dump_data) and end_t_marker and _idx(dump_data[i][2]) < end_t_marker:
                        i += 1
                    continue

                if is_in_skip_range(t):
                    i += 1
                    continue

                # Toggle markers at boundaries
                if t in strike_ends and strike_open:
                    result.append('[/STRIKE]'); strike_open = False
                if t in hl_ends and hl_open:
                    result.append('[/HL]'); hl_open = None
                if t in strike_starts and not strike_open:
                    result.append('[STRIKE]'); strike_open = True
                if t in hl_starts and hl_open is None:
                    color = hl_starts[t]
                    result.append(f'[HL:{color}]'); hl_open = color

                if key == 'text':
                    result.append(value)
                elif key == 'image':
                    if value.startswith('img_'):
                        filename = value[4:]
                        if '#' in filename:
                            filename = filename[:filename.index('#')]
                        if filename in self.image_widths:
                            width = self.image_widths[filename]
                            result.append(f"[IMAGE:{filename}:{width}]")
                        else:
                            result.append(f"[IMAGE:{filename}]")
                    # vidthumb_ images are covered by the FILE marker above
                i += 1

            if strike_open:
                result.append('[/STRIKE]')
            if hl_open:
                result.append('[/HL]')

            return "".join(result)
        except Exception as e:
            print(f"Error serializing range: {e}")
            return ""

    def _insert_serialized_at_cursor(self, content, source_notebook=None):
        """Insert marker-format content at the current INSERT position.
        Copies missing files from source_notebook attachments to the current
        notebook attachments if source_notebook is given and differs.
        """
        if not content:
            return

        image_pattern = re.compile(r'\[IMAGE:([^:\]]+)(?::(\d+))?\]')
        file_pattern = re.compile(r'\[FILE:([^\]]+)\]')
        hl_pattern = re.compile(r'\[HL:(\w+)\]')

        parts = re.split(
            r'(\[IMAGE:[^\]]+\]|\[FILE:[^\]]+\]|\[STRIKE\]|\[/STRIKE\]|\[HL:\w+\]|\[/HL\])',
            content)

        target_attachments = self.get_attachments_path()
        source_attachments = None
        if source_notebook and source_notebook != self.current_notebook:
            source_attachments = os.path.join(self.notebooks_dir, source_notebook, "attachments")

        def ensure_file_in_target(filename):
            target_path = os.path.join(target_attachments, filename)
            if os.path.exists(target_path):
                return target_path
            if source_attachments:
                source_path = os.path.join(source_attachments, filename)
                if os.path.exists(source_path):
                    try:
                        if os.path.isdir(source_path):
                            shutil.copytree(source_path, target_path)
                        else:
                            shutil.copy2(source_path, target_path)
                        return target_path
                    except Exception as e:
                        print(f"Error copying {filename} from source notebook: {e}")
            return None

        in_strike = False
        in_hl = None
        for part in parts:
            if not part:
                continue
            if part == '[STRIKE]':
                in_strike = True
                continue
            if part == '[/STRIKE]':
                in_strike = False
                continue
            hl_m = hl_pattern.match(part)
            if hl_m:
                in_hl = hl_m.group(1)
                continue
            if part == '[/HL]':
                in_hl = None
                continue

            img_m = image_pattern.match(part)
            file_m = file_pattern.match(part)
            if img_m:
                filename = img_m.group(1)
                width = int(img_m.group(2)) if img_m.group(2) else None
                target_path = ensure_file_in_target(filename)
                if target_path:
                    self.insert_image_at_cursor(target_path, filename, position=tk.INSERT, width=width)
                else:
                    self.text_area.insert(tk.INSERT, part)
            elif file_m:
                filename = file_m.group(1)
                target_path = ensure_file_in_target(filename)
                if target_path:
                    self.insert_file_link(filename)
                else:
                    self.text_area.insert(tk.INSERT, part)
            else:
                if in_strike or in_hl:
                    seg_start = self.text_area.index(tk.INSERT)
                    self.text_area.insert(tk.INSERT, part)
                    seg_end = self.text_area.index(tk.INSERT)
                    if in_strike:
                        self.text_area.tag_add("strikethrough", seg_start, seg_end)
                    if in_hl:
                        self.text_area.tag_add(f"highlight_{in_hl}", seg_start, seg_end)
                else:
                    self.text_area.insert(tk.INSERT, part)

    def handle_copy(self, event=None):
        """Handle copy - detect if copying a file/image link, copy actual file to clipboard"""
        try:
            # 0) Mixed text + media selection → use rich-copy serialization that
            #    preserves headings/text alongside images and file/video previews.
            if self.text_area.tag_ranges(tk.SEL):
                sel_start = self.text_area.index(tk.SEL_FIRST)
                sel_end = self.text_area.index(tk.SEL_LAST)
                has_real_text = False  # Text that is NOT part of a file/image label
                has_media = False
                try:
                    for kind, value, idx in self.text_area.dump(
                            sel_start, sel_end, text=True, image=True):
                        if kind == "text" and value and value.strip():
                            try:
                                tags_at = self.text_area.tag_names(idx)
                            except Exception:
                                tags_at = ()
                            if not any(
                                t.startswith("file_") or t.startswith("imgname_")
                                or t.startswith("icon_") or t.startswith("url_preview_")
                                for t in tags_at
                            ):
                                has_real_text = True
                        elif kind == "image":
                            has_media = True
                        if has_real_text and has_media:
                            break
                except Exception:
                    pass

                if has_real_text and has_media:
                    serialized = self._serialize_range(sel_start, sel_end)
                    if serialized:
                        marker = f"[INTERNAL:RICH:{self.current_notebook}]{serialized}[/INTERNAL:RICH]"
                        self.root.clipboard_clear()
                        self.root.clipboard_append(marker)
                        self.copied_internal_link = ("rich", None)
                        return "break"

            # Build the list of (kind, internal_filename) found in or near the selection
            found = None  # First match wins; ("file"|"image", internal_filename)

            # 1) Scan the entire selection range with dump() — most reliable for
            #    selections that span multiple lines or include headings + media.
            if self.text_area.tag_ranges(tk.SEL):
                sel_start = self.text_area.index(tk.SEL_FIRST)
                sel_end = self.text_area.index(tk.SEL_LAST)
                try:
                    for kind, value, _idx in self.text_area.dump(
                            sel_start, sel_end, tag=True, image=True):
                        if kind == "tagon":
                            if value.startswith("file_"):
                                found = ("file", value[5:]); break
                            elif value.startswith("icon_"):
                                found = ("file", value[5:]); break
                            elif value.startswith("imgname_"):
                                found = ("image", value[8:]); break
                            elif value.startswith("imgtag_"):
                                found = ("image", value[7:]); break
                        elif kind == "image":
                            # Embedded image — extract filename from img name
                            name = value
                            if name.startswith("img_"):
                                # strip optional "#N" suffix added for duplicates
                                fname = name[4:]
                                if "#" in fname:
                                    fname = fname[:fname.index("#")]
                                found = ("image", fname); break
                            elif name.startswith("vidthumb_"):
                                fname = name[9:]
                                if "#" in fname:
                                    fname = fname[:fname.index("#")]
                                found = ("file", fname); break
                except Exception:
                    pass

            # 2) Fallback: check tag_names at a few discrete positions (cursor,
            #    selection boundaries) — catches cases where the selection is
            #    collapsed or the user invoked copy on a single tag.
            if found is None:
                positions_to_check = []
                if self.text_area.tag_ranges(tk.SEL):
                    sel_start = self.text_area.index(tk.SEL_FIRST)
                    sel_end = self.text_area.index(tk.SEL_LAST)
                    positions_to_check.append(sel_start)
                    positions_to_check.append(sel_end)
                    positions_to_check.append(f"{sel_start}+1c")
                positions_to_check.append(self.text_area.index(tk.INSERT))

                for pos in positions_to_check:
                    try:
                        for tag in self.text_area.tag_names(pos):
                            if tag.startswith("file_"):
                                found = ("file", tag[5:]); break
                            elif tag.startswith("icon_"):
                                found = ("file", tag[5:]); break
                            elif tag.startswith("imgname_"):
                                found = ("image", tag[8:]); break
                            elif tag.startswith("imgtag_"):
                                found = ("image", tag[7:]); break
                    except Exception:
                        pass
                    if found is not None:
                        break

            if found is not None:
                kind, internal_filename = found
                marker = f"[INTERNAL:{kind}:{internal_filename}]"
                self.copy_file_to_clipboard(internal_filename, internal_marker=marker)
                self.copied_internal_link = (kind, internal_filename)
                return "break"

        except Exception as e:
            print(f"Error in handle_copy: {e}")

        # Check if selection contains strikethrough - copy as RTF to preserve formatting
        if self.text_area.tag_ranges(tk.SEL):
            if self.copy_with_strikethrough_rtf():
                self.copied_internal_link = None
                return "break"

        # If selection contains embedded images, try to copy image as internal link
        if self._selection_has_images():
            if self.text_area.tag_ranges(tk.SEL):
                sel_start = self.text_area.index(tk.SEL_FIRST)
                sel_end = self.text_area.index(tk.SEL_LAST)
                # Scan selection range for image tags
                img_filename = None
                for kind, value, idx in self.text_area.dump(sel_start, sel_end, tag=True, image=True):
                    if kind == "tagon" and (value.startswith("imgtag_") or value.startswith("imgname_")):
                        img_filename = value.split("_", 1)[1]
                        break
                if img_filename:
                    marker = f"[INTERNAL:image:{img_filename}]"
                    self.root.clipboard_clear()
                    self.root.clipboard_append(marker)
                    self.copied_internal_link = ("image", img_filename)
                else:
                    # Fallback: copy plain text to prevent Tk freeze
                    sel_text = self.text_area.get(tk.SEL_FIRST, tk.SEL_LAST)
                    self.root.clipboard_clear()
                    self.root.clipboard_append(sel_text)
                    self.copied_internal_link = None
            return "break"

        # Clear internal link when copying regular text
        self.copied_internal_link = None

        # Let default copy behavior handle regular text
        return None

    def copy_with_strikethrough_rtf(self):
        """Copy selected text as RTF with strikethrough formatting to clipboard.
        Returns True if RTF was set on clipboard, False if no strikethrough in selection.
        """
        sel_start = self.text_area.index(tk.SEL_FIRST)
        sel_end = self.text_area.index(tk.SEL_LAST)

        # Get strikethrough ranges
        strike_ranges = self.text_area.tag_ranges("strikethrough")
        if not strike_ranges:
            return False

        # Check if any strikethrough range overlaps with selection
        has_overlap = False
        for i in range(0, len(strike_ranges), 2):
            s = str(strike_ranges[i])
            e = str(strike_ranges[i + 1])
            if self.text_area.compare(s, "<", sel_end) and self.text_area.compare(e, ">", sel_start):
                has_overlap = True
                break

        if not has_overlap:
            return False

        # Build intervals: list of (start, end, is_strike)
        intervals = []
        current = sel_start

        for i in range(0, len(strike_ranges), 2):
            s = str(strike_ranges[i])
            e = str(strike_ranges[i + 1])

            if self.text_area.compare(e, "<=", sel_start):
                continue
            if self.text_area.compare(s, ">=", sel_end):
                break

            clip_s = s if self.text_area.compare(s, ">", sel_start) else sel_start
            clip_e = e if self.text_area.compare(e, "<", sel_end) else sel_end

            if self.text_area.compare(current, "<", clip_s):
                intervals.append((current, clip_s, False))

            intervals.append((clip_s, clip_e, True))
            current = clip_e

        if self.text_area.compare(current, "<", sel_end):
            intervals.append((current, sel_end, False))

        # Build RTF content
        fs = self.current_font_size * 2  # RTF uses half-points
        rtf = r'{\rtf1\ansi\deff0'
        rtf += r'{\fonttbl{\f0 Arial;}}'
        rtf += r'{\colortbl;\red136\green136\blue136;}'  # color index 1 = #888888
        rtf += f'\\f0\\fs{fs} '

        for start, end, is_strike in intervals:
            text = self.text_area.get(start, end)
            escaped = self._rtf_escape(text)
            if is_strike:
                rtf += r'{\strike\cf1 ' + escaped + r'}'
            else:
                rtf += escaped

        rtf += '}'

        # Set RTF on macOS clipboard via osascript
        try:
            import tempfile
            tmp_path = None
            with tempfile.NamedTemporaryFile(suffix='.rtf', delete=False, mode='wb') as f:
                f.write(rtf.encode('utf-8'))
                tmp_path = f.name

            subprocess.run(
                ['osascript', '-e',
                 f'set the clipboard to (read POSIX file "{tmp_path}" as «class RTF »)'],
                check=True, capture_output=True
            )
            return True
        except Exception as ex:
            print(f"Error setting RTF clipboard: {ex}")
            return False
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except:
                    pass

    def _rtf_escape(self, text):
        """Escape text for RTF format, handling Unicode"""
        result = []
        for ch in text:
            if ch == '\\':
                result.append('\\\\')
            elif ch == '{':
                result.append('\\{')
            elif ch == '}':
                result.append('\\}')
            elif ch == '\n':
                result.append('\\line ')
            elif ord(ch) > 127:
                result.append(f'\\u{ord(ch)}?')
            else:
                result.append(ch)
        return ''.join(result)

    def on_before_delete(self, event=None):
        """Handle delete/backspace - let Tk native undo track it"""
        self.content_modified = True
        # Schedule auto-save after deletion
        self.schedule_auto_save()
        return None  # Let the event continue

    def _selection_has_images(self):
        """Check whether the current selection contains any embedded images."""
        if not self.text_area.tag_ranges(tk.SEL):
            return False
        sel_start = self.text_area.index(tk.SEL_FIRST)
        sel_end = self.text_area.index(tk.SEL_LAST)
        # dump is the reliable way to detect images inside a range
        for kind, value, _ in self.text_area.dump(sel_start, sel_end, image=True):
            if kind == "image":
                return True
        return False

    def on_before_cut(self, event=None):
        """Handle cut - copy file/image/rich content to clipboard, then delete the selection.
        Delegates clipboard logic to handle_copy so all formats stay in sync."""
        self.save_undo_state()
        self.content_modified = True

        # Nothing selected → nothing to cut
        if not self.text_area.tag_ranges(tk.SEL):
            return None

        # Reuse the unified copy pipeline (handles rich, file, image, RTF strike).
        copy_result = None
        try:
            copy_result = self.handle_copy(event)
        except Exception as e:
            print(f"Error in on_before_cut → handle_copy: {e}")

        if copy_result == "break":
            # handle_copy already put content on the clipboard; now delete the selection
            try:
                if self.text_area.tag_ranges(tk.SEL):
                    self.text_area.delete(tk.SEL_FIRST, tk.SEL_LAST)
            except Exception as e:
                print(f"Error deleting selection in cut: {e}")
            self.schedule_auto_save()
            self._schedule_markdown_update()
            return "break"

        # Plain-text path. If the selection contains embedded images, the
        # default Tk <<Cut>> can freeze on the image objects, so handle the
        # delete ourselves after putting plain text on the clipboard.
        if self._selection_has_images():
            try:
                sel_text = self.text_area.get(tk.SEL_FIRST, tk.SEL_LAST)
                self.root.clipboard_clear()
                self.root.clipboard_append(sel_text)
                self.text_area.delete(tk.SEL_FIRST, tk.SEL_LAST)
            except Exception as e:
                print(f"Error in plain-text cut fallback: {e}")
            self.schedule_auto_save()
            self._schedule_markdown_update()
            return "break"

        # Pure plain-text — let the default Tk cut handler do its thing.
        self.schedule_auto_save()
        self._schedule_markdown_update()
        return None

    def on_key_press(self, event=None):
        """Handle key press - track modification and schedule updates.
        Normal text undo is handled by Tk's native undo (edit_undo).
        """
        # Skip during programmatic paste to avoid cascade
        if getattr(self, 'is_pasting', False):
            return None

        # Ignore modifier keys and special keys
        if event and event.keysym in ('Shift_L', 'Shift_R', 'Control_L', 'Control_R',
                                       'Alt_L', 'Alt_R', 'Command', 'Meta_L', 'Meta_R',
                                       'Caps_Lock', 'Escape', 'Up', 'Down', 'Left', 'Right',
                                       'Home', 'End', 'Page_Up', 'Page_Down'):
            return None

        # Ignore keyboard shortcuts with modifiers (handled separately)
        if event and event.keysym in ('x', 'X', 'c', 'C', 'v', 'V',
                                       'z', 'Z', 'y', 'Y', 's', 'S'):
            if event.state & ~0x3:  # any modifier beyond Shift/CapsLock
                return None

        # Mark content as modified
        self.content_modified = True

        # Schedule auto-save after typing stops
        self.schedule_auto_save()

        # Schedule markdown re-render
        self._schedule_markdown_update()

        return None  # Let the event continue

    def schedule_auto_save(self):
        """Schedule auto-save after a delay. Resets timer if called again before save."""
        # Cancel any pending auto-save
        if self.auto_save_timer_id is not None:
            self.root.after_cancel(self.auto_save_timer_id)

        # Schedule new auto-save
        self.auto_save_timer_id = self.root.after(self.auto_save_delay_ms, self.auto_save)

    def auto_save(self):
        """Perform auto-save if content has changed since last save."""
        self.auto_save_timer_id = None

        try:
            current_content = self.get_content_with_markers()

            # Only save if content has actually changed
            if self.last_saved_content is None or current_content != self.last_saved_content:
                self.save_notes()
                self.last_saved_content = current_content
        except Exception as e:
            print(f"Error in auto-save: {e}")

    def save_undo_state(self):
        """Save current state to custom undo stack.
        Called before complex operations (paste image/file, strikethrough)
        that Tk native undo can't fully handle.
        """
        if self.is_restoring:
            return

        # Flush Tk native undo stack so it won't interfere with custom restore.
        # Any pending native edits become part of the custom snapshot.
        try:
            self.text_area.edit_reset()
        except tk.TclError:
            pass

        # Get current content with markers
        content = self.get_content_with_markers()
        cursor_pos = self.text_area.index(tk.INSERT)

        # Don't save if same as last state (skip lightweight highlight entries)
        if self.undo_stack and isinstance(self.undo_stack[-1], tuple) \
                and len(self.undo_stack[-1]) == 2 and self.undo_stack[-1][0] == content:
            return

        # Save state
        self.undo_stack.append((content, cursor_pos))

        # Limit stack size
        while len(self.undo_stack) > self.max_undo_levels:
            self.undo_stack.pop(0)

        # Clear redo stack when new action is performed
        self.redo_stack.clear()

    def handle_undo_redo(self, event=None):
        """Dispatch to undo or redo based on Shift modifier.
        On macOS, Cmd+Shift+Z often matches <Command-z> instead of <Command-Shift-z>,
        so we detect Shift here to ensure redo works correctly.
        """
        if event and (event.state & 0x1):  # Shift is pressed → redo
            return self.redo(event)
        else:
            return self.undo(event)

    def _push_paste_range_undo(self, before_pos, after_pos, redo_marker=None):
        """Push a lightweight paste undo: just delete the inserted range on undo."""
        # Flush Tk native undo so it doesn't interfere
        try:
            self.text_area.edit_reset()
        except tk.TclError:
            pass
        self.undo_stack.append(("paste_range", before_pos, after_pos, redo_marker))
        self.redo_stack.clear()

    def undo(self, event=None):
        """Undo last action — use Tk native undo first (instant for text edits),
        fall back to custom stack for complex operations (image/file paste)."""
        # Try Tk native undo first (handles normal text typing/deletion)
        try:
            self.text_area.edit_undo()
            self._schedule_markdown_update()
            self.content_modified = True
            return "break"
        except tk.TclError:
            pass  # Native undo stack empty, try custom stack

        # Fall back to custom undo stack (for image/file/strikethrough operations)
        if not self.undo_stack:
            return "break"

        entry = self.undo_stack.pop()

        # Lightweight highlight undo (tag-only, no content rebuild)
        if isinstance(entry, tuple) and len(entry) == 3 and entry[0] == "highlight":
            _, undo_op, redo_op = entry
            self.redo_stack.append(("highlight", redo_op, undo_op))
            undo_op()
            self.content_modified = True
            self.schedule_auto_save()
            return "break"

        # Lightweight paste-range undo (just delete the inserted range)
        if isinstance(entry, tuple) and len(entry) == 4 and entry[0] == "paste_range":
            _, before_pos, after_pos, redo_marker = entry
            # Save what's being deleted for redo
            self.redo_stack.append(("paste_range", before_pos, after_pos, redo_marker))
            self.text_area.delete(before_pos, after_pos)
            self.text_area.mark_set(tk.INSERT, before_pos)
            try:
                self.text_area.edit_reset()
            except tk.TclError:
                pass
            self._schedule_markdown_update()
            self.content_modified = True
            self.schedule_auto_save()
            return "break"

        # Full content restore (legacy: image/file/strikethrough)
        content, cursor_pos = entry
        current_content = self.get_content_with_markers()
        current_cursor = self.text_area.index(tk.INSERT)
        self.redo_stack.append((current_content, current_cursor))
        self.restore_content(content, cursor_pos)

        return "break"

    def redo(self, event=None):
        """Redo last undone action — use Tk native redo first,
        fall back to custom stack."""
        # Try Tk native redo first
        try:
            self.text_area.edit_redo()
            self._schedule_markdown_update()
            self.content_modified = True
            return "break"
        except tk.TclError:
            pass  # Native redo stack empty, try custom stack

        # Fall back to custom redo stack
        if not self.redo_stack:
            return "break"

        entry = self.redo_stack.pop()

        # Lightweight highlight redo (tag-only, no content rebuild)
        if isinstance(entry, tuple) and len(entry) == 3 and entry[0] == "highlight":
            _, redo_op, undo_op = entry
            self.undo_stack.append(("highlight", undo_op, redo_op))
            redo_op()
            self.content_modified = True
            self.schedule_auto_save()
            return "break"

        # Lightweight paste-range redo (re-paste the content)
        if isinstance(entry, tuple) and len(entry) == 4 and entry[0] == "paste_range":
            _, before_pos, _after_pos, redo_marker = entry
            self.text_area.mark_set(tk.INSERT, before_pos)
            if redo_marker and redo_marker.startswith('[INTERNAL:RICH:') \
                    and redo_marker.endswith('[/INTERNAL:RICH]'):
                rich_match = re.match(
                    r'^\[INTERNAL:RICH:([^\]]*)\](.*)\[/INTERNAL:RICH\]$',
                    redo_marker, re.DOTALL)
                if rich_match:
                    self._insert_serialized_at_cursor(
                        rich_match.group(2), source_notebook=rich_match.group(1))
            elif redo_marker and redo_marker.startswith('[INTERNAL:'):
                self.paste_internal_link(redo_marker)
            # Push back to undo stack; after_pos may change so recalculate
            new_after = self.text_area.index(tk.INSERT)
            self.undo_stack.append(("paste_range", before_pos, new_after, redo_marker))
            try:
                self.text_area.edit_reset()
            except tk.TclError:
                pass
            self._schedule_markdown_update()
            self.content_modified = True
            self.schedule_auto_save()
            return "break"

        # Full content restore (legacy)
        content, cursor_pos = entry
        current_content = self.get_content_with_markers()
        current_cursor = self.text_area.index(tk.INSERT)
        self.undo_stack.append((current_content, current_cursor))
        self.restore_content(content, cursor_pos)

        return "break"

    def restore_content(self, content, cursor_pos):
        """Restore content from saved state (used by custom undo for complex operations)"""
        self.is_restoring = True
        try:
            # Save scroll position before restore
            scroll_pos = self.text_area.yview()

            # Clear text area
            self.text_area.delete("1.0", tk.END)

            # Clear undo records immediately to free any image name reservations
            # (undo records from the delete above may hold image names)
            self.text_area.edit_reset()

            # Clear URL tags (images are kept in self.images)
            self.url_tags.clear()
            self._url_preview_tags.clear()

            # Reload content
            self.load_content_with_images(content)

            # Restore cursor position without scrolling
            try:
                self.text_area.mark_set(tk.INSERT, cursor_pos)
            except:
                pass

            # Restore scroll position instead of jumping to cursor
            self.text_area.yview_moveto(scroll_pos[0])

            # Reset Tk native undo stack (the full rebuild shouldn't be undoable)
            self.text_area.edit_reset()
        finally:
            self.is_restoring = False

    def handle_tab(self, event=None):
        """Handle Tab key - indent selected lines by 4 spaces"""
        # Check if there's a selection
        if self.text_area.tag_ranges(tk.SEL):
            # Get selection range
            sel_start = self.text_area.index(tk.SEL_FIRST)
            sel_end = self.text_area.index(tk.SEL_LAST)

            # Get line numbers
            start_line = int(sel_start.split('.')[0])
            end_line = int(sel_end.split('.')[0])

            # Add 4 spaces to the beginning of each selected line
            for line_num in range(start_line, end_line + 1):
                self.text_area.insert(f"{line_num}.0", "    ")

            # Restore selection (adjusted for added spaces)
            self.text_area.tag_remove(tk.SEL, "1.0", tk.END)
            self.text_area.tag_add(tk.SEL, f"{start_line}.0", f"{end_line}.end")

            return "break"
        else:
            # No selection - insert 4 spaces at cursor
            self.text_area.insert(tk.INSERT, "    ")
            return "break"

    def handle_shift_tab(self, event=None):
        """Handle Shift+Tab - unindent selected lines by up to 4 spaces"""
        # Check if there's a selection
        if self.text_area.tag_ranges(tk.SEL):
            # Get selection range
            sel_start = self.text_area.index(tk.SEL_FIRST)
            sel_end = self.text_area.index(tk.SEL_LAST)

            # Get line numbers
            start_line = int(sel_start.split('.')[0])
            end_line = int(sel_end.split('.')[0])

            # Remove up to 4 spaces from the beginning of each selected line
            for line_num in range(start_line, end_line + 1):
                line_start = f"{line_num}.0"
                line_content = self.text_area.get(line_start, f"{line_num}.end")

                # Count leading spaces (up to 4)
                spaces_to_remove = 0
                for char in line_content[:4]:
                    if char == ' ':
                        spaces_to_remove += 1
                    else:
                        break

                # Remove the leading spaces
                if spaces_to_remove > 0:
                    self.text_area.delete(line_start, f"{line_num}.{spaces_to_remove}")

            # Restore selection
            self.text_area.tag_remove(tk.SEL, "1.0", tk.END)
            self.text_area.tag_add(tk.SEL, f"{start_line}.0", f"{end_line}.end")

            return "break"
        else:
            # No selection - try to remove up to 4 spaces before cursor
            cursor_pos = self.text_area.index(tk.INSERT)
            line_num = cursor_pos.split('.')[0]
            line_start = f"{line_num}.0"
            line_content = self.text_area.get(line_start, f"{line_num}.end")

            # Count leading spaces (up to 4)
            spaces_to_remove = 0
            for char in line_content[:4]:
                if char == ' ':
                    spaces_to_remove += 1
                else:
                    break

            if spaces_to_remove > 0:
                self.text_area.delete(line_start, f"{line_num}.{spaces_to_remove}")

            return "break"

    def handle_paste(self, event):
        """Handle paste event - check for images or files in clipboard"""
        if not PIL_AVAILABLE:
            return  # Let default paste behavior handle text

        # Guard: suppress on_key_press cascade during programmatic insert
        self.is_pasting = True
        try:
            return self._do_paste()
        finally:
            self.is_pasting = False
            self._schedule_markdown_update()

    def _do_paste(self):
        """Internal paste implementation."""
        self.content_modified = True

        # Fast check: try to get text from clipboard using Tkinter (instant, 0ms)
        might_be_file = False
        clipboard_text = None
        try:
            clipboard_text = self.root.clipboard_get()
            if clipboard_text:
                text = clipboard_text.strip()

                # Check for rich-format internal marker (mixed text + media)
                if text.startswith('[INTERNAL:RICH:') and text.endswith('[/INTERNAL:RICH]'):
                    rich_match = re.match(
                        r'^\[INTERNAL:RICH:([^\]]*)\](.*)\[/INTERNAL:RICH\]$',
                        text, re.DOTALL)
                    if rich_match:
                        source_notebook = rich_match.group(1)
                        inner_content = rich_match.group(2)
                        try:
                            self.text_area.tag_remove(tk.SEL, "1.0", tk.END)
                        except tk.TclError:
                            pass
                        before_pos = self.text_area.index(tk.INSERT)
                        try:
                            self._insert_serialized_at_cursor(
                                inner_content, source_notebook=source_notebook)
                        except Exception as e:
                            print(f"Error pasting rich content: {e}")
                        after_pos = self.text_area.index(tk.INSERT)
                        self._push_paste_range_undo(before_pos, after_pos, text)
                        self.schedule_auto_save()
                        return "break"

                # Check for internal link marker in clipboard
                if text.startswith('[INTERNAL:') and text.endswith(']'):
                    # Deselect to avoid interfering with the original content
                    try:
                        self.text_area.tag_remove(tk.SEL, "1.0", tk.END)
                    except tk.TclError:
                        pass
                    # Lightweight undo for image/file paste: record range
                    before_pos = self.text_area.index(tk.INSERT)
                    if self.paste_internal_link(text):
                        after_pos = self.text_area.index(tk.INSERT)
                        self._push_paste_range_undo(before_pos, after_pos, text)
                        self.schedule_auto_save()
                        return "break"
                    # File missing in current notebook attachments — likely a
                    # cross-notebook paste. Fall back to importing via the
                    # accompanying file URL on the system clipboard.
                    if platform.system() == "Darwin":
                        file_paths = self.get_clipboard_files_fast()
                        if file_paths:
                            before_pos = self.text_area.index(tk.INSERT)
                            self.paste_files(file_paths)
                            after_pos = self.text_area.index(tk.INSERT)
                            self._push_paste_range_undo(before_pos, after_pos)
                            self.schedule_auto_save()
                            return "break"

                # Check if it looks like a file path that exists
                if text.startswith('/') and os.path.exists(text):
                    might_be_file = True
                # Check if it looks like a filename (has common extension) - but not URLs
                elif '.' in text and not text.startswith('http://') and not text.startswith('https://'):
                    ext = os.path.splitext(text)[1].lower()
                    common_exts = {'.txt', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
                                   '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg',
                                   '.mp3', '.mp4', '.mov', '.avi', '.mkv', '.wav', '.m4a',
                                   '.zip', '.rar', '.7z', '.tar', '.gz',
                                   '.py', '.js', '.html', '.css', '.json', '.xml', '.md',
                                   '.app', '.dmg', '.pkg', '.exe'}
                    if ext in common_exts:
                        might_be_file = True
        except tk.TclError:
            # No text in clipboard, definitely image or files
            might_be_file = True

        # Check for files (macOS)
        if might_be_file and platform.system() == "Darwin":
            file_paths = self.get_clipboard_files_fast()
            if file_paths:
                before_pos = self.text_area.index(tk.INSERT)
                self.paste_files(file_paths)
                after_pos = self.text_area.index(tk.INSERT)
                self._push_paste_range_undo(before_pos, after_pos)
                self.schedule_auto_save()
                return "break"

        # Check for images (screenshot etc) — but ONLY if the clipboard doesn't
        # already contain valid text.  ImageGrab.grabclipboard() is slow on macOS
        # (50-200ms) and is unnecessary when pasting plain text.
        if not clipboard_text:
            try:
                image = ImageGrab.grabclipboard()
                if image is not None:
                    if isinstance(image, Image.Image):
                        before_pos = self.text_area.index(tk.INSERT)
                        self.paste_image(image)
                        after_pos = self.text_area.index(tk.INSERT)
                        self._push_paste_range_undo(before_pos, after_pos)
                        self.schedule_auto_save()
                        return "break"
                    elif isinstance(image, list):
                        before_pos = self.text_area.index(tk.INSERT)
                        self.paste_files(image)
                        after_pos = self.text_area.index(tk.INSERT)
                        self._push_paste_range_undo(before_pos, after_pos)
                        self.schedule_auto_save()
                        return "break"
            except Exception as e:
                print(f"Error in ImageGrab: {e}")

        # Handle text paste with URL detection
        if clipboard_text:
            # Delete selected text if any
            try:
                if self.text_area.tag_ranges(tk.SEL):
                    self.text_area.delete(tk.SEL_FIRST, tk.SEL_LAST)
            except:
                pass

            # Insert text with URL detection at cursor position
            cursor_pos = self.text_area.index(tk.INSERT)

            # Check if text contains URLs
            if self.url_pattern.search(clipboard_text):
                # Insert text with URL tagging
                self.insert_text_with_urls_at_cursor(clipboard_text)
            else:
                # No URLs, just insert normally
                self.text_area.insert(tk.INSERT, clipboard_text)

            self.schedule_auto_save()
            return "break"

        # Let default paste behavior handle (fallback)
        return None

    def paste_internal_link(self, marker_text):
        """Paste an internal file/image link"""
        # Parse marker: [INTERNAL:type:filename]
        try:
            content = marker_text[10:-1]  # Remove [INTERNAL: and ]
            parts = content.split(':', 1)
            if len(parts) == 2:
                link_type, internal_filename = parts
                filepath = os.path.join(self.get_attachments_path(), internal_filename)

                if os.path.exists(filepath):
                    if link_type == "image":
                        self.insert_image_at_cursor(filepath, internal_filename)
                        self.text_area.insert(tk.INSERT, "\n")
                    elif link_type == "file":
                        self.insert_file_link(internal_filename)
                    return True
        except Exception as e:
            print(f"Error pasting internal link: {e}")

        return False

    def get_clipboard_files_fast(self):
        """Fast check for file paths in clipboard using PyObjC"""
        try:
            # Try using PyObjC directly (much faster than AppleScript)
            from AppKit import NSPasteboard, NSFilenamesPboardType
            pb = NSPasteboard.generalPasteboard()

            # Check if clipboard contains files
            if NSFilenamesPboardType in pb.types():
                paths = pb.propertyListForType_(NSFilenamesPboardType)
                if paths:
                    return list(paths)
        except ImportError:
            # PyObjC not available, fall back to slower method
            return self.get_clipboard_files_slow()
        except Exception as e:
            print(f"Error in fast clipboard check: {e}")

        return None

    def get_clipboard_files_slow(self):
        """Fallback: Get file paths from clipboard using AppleScript (slower)"""
        try:
            script = '''
            use framework "AppKit"
            set thePasteboard to current application's NSPasteboard's generalPasteboard()
            set theTypes to thePasteboard's types() as list

            if theTypes contains "public.file-url" or theTypes contains "NSFilenamesPboardType" then
                set fileURLs to thePasteboard's readObjectsForClasses:{current application's NSURL} options:(missing value)
                if fileURLs is not missing value and (count of fileURLs) > 0 then
                    set thePaths to ""
                    repeat with aURL in fileURLs
                        set thePaths to thePaths & (aURL's |path|() as text) & linefeed
                    end repeat
                    return thePaths
                end if
            end if
            return ""
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=1  # Add timeout to prevent hanging
            )
            if result.returncode == 0 and result.stdout.strip():
                paths = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
                if paths and all(os.path.exists(p) for p in paths):
                    return paths
        except subprocess.TimeoutExpired:
            print("Clipboard check timed out")
        except Exception as e:
            print(f"Error getting clipboard files: {e}")

        return None

    def paste_image(self, image):
        """Save image and insert into text area"""
        try:
            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            filename = f"img_{timestamp}_{unique_id}.png"
            filepath = os.path.join(self.get_attachments_path(), filename)

            # Save image
            image.save(filepath, "PNG")

            # Insert image into text area (includes filename label)
            self.insert_image_at_cursor(filepath, filename)

            # Insert a newline after label for better layout
            self.text_area.insert(tk.INSERT, "\n")

        except Exception as e:
            print(f"Error pasting image: {e}")

    def paste_files(self, file_paths):
        """Handle pasted file paths"""
        image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}

        for file_path in file_paths:
            # Check if path exists (file or directory)
            if not os.path.exists(file_path):
                continue

            _, ext = os.path.splitext(file_path)
            ext = ext.lower()

            # Generate unique internal filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            original_name = os.path.basename(file_path)
            base_name, file_ext = os.path.splitext(original_name)
            internal_filename = f"{base_name}_{timestamp}_{unique_id}{file_ext}"
            new_filepath = os.path.join(self.get_attachments_path(), internal_filename)

            try:
                # Copy file or directory to attachments directory
                if os.path.isdir(file_path):
                    # For directories (like .app bundles), use copytree
                    shutil.copytree(file_path, new_filepath)
                else:
                    # For regular files
                    shutil.copy2(file_path, new_filepath)

                # Save original name and path mapping
                self.filename_map[internal_filename] = {
                    "name": original_name,
                    "path": os.path.abspath(file_path)
                }
                self.save_filename_map()

                if ext in image_extensions and not os.path.isdir(file_path):
                    # Insert as image
                    self.insert_image_at_cursor(new_filepath, internal_filename)
                else:
                    # Insert as file link (display original name)
                    self.insert_file_link(internal_filename)

            except Exception as e:
                print(f"Error copying file {file_path}: {e}")

    def insert_image_at_cursor(self, filepath, filename, position=None, width=None, thumbnail=False):
        """Insert image at specified position (default: cursor) with optional custom width

        Args:
            thumbnail: If True, use small thumbnail for fast loading
        """
        if not PIL_AVAILABLE:
            return

        if position is None:
            position = tk.INSERT

        # Deferred mode: insert tiny placeholder, queue real load for later
        if getattr(self, '_fast_load_mode', False) and not thumbnail:
            try:
                if not hasattr(self, '_placeholder_photo'):
                    self._placeholder_photo = ImageTk.PhotoImage(
                        Image.new('RGBA', (1, 1), (0, 0, 0, 0)))
                image_id = f"img_{filename}"
                self.images[image_id] = self._placeholder_photo
                try:
                    self.text_area.index(image_id)
                    self.text_area.delete(image_id)
                except tk.TclError:
                    pass
                self.text_area.image_create(position, image=self._placeholder_photo, name=image_id)
                if width is not None:
                    self.image_widths[filename] = width
                self._deferred_images.append((filepath, filename, width))
                return
            except Exception:
                pass  # Fall through to normal loading

        try:
            # Load image
            image = Image.open(filepath)
            original_width = image.width

            # Determine target width
            if thumbnail:
                # Fast thumbnail mode: use small size and fast algorithm
                target_width = 80
            elif width is not None:
                target_width = width
            elif filename in self.image_widths:
                target_width = self.image_widths[filename]
            else:
                target_width = self.max_image_width

            # Clamp target width to valid range
            target_width = max(50, min(800, target_width))

            # Resize if needed
            if image.width != target_width:
                ratio = target_width / image.width
                new_height = int(image.height * ratio)
                # Use NEAREST for thumbnails, LANCZOS for normal
                resample = Image.Resampling.NEAREST if thumbnail else Image.Resampling.LANCZOS
                image = image.resize((target_width, new_height), resample)

            # Store the width for this image
            # In thumbnail mode, preserve the saved width (from file) instead of thumbnail size
            if thumbnail and width is not None:
                self.image_widths[filename] = width
            else:
                self.image_widths[filename] = image.width

            # Cache thumbnail for fast loading on future notebook switches
            if not thumbnail:
                try:
                    base = os.path.splitext(filename)[0]
                    tw = image.width
                    thumb_name = f"_thumb_{base}_{tw}.jpg"
                    thumb_path = os.path.join(self.get_attachments_path(), thumb_name)
                    if not os.path.exists(thumb_path):
                        save_img = image.convert('RGB') if image.mode in ('RGBA', 'P', 'LA') else image
                        save_img.save(thumb_path, 'JPEG', quality=85)
                except Exception:
                    pass

            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(image)

            # Store reference to prevent garbage collection
            image_id = f"img_{filename}"

            # Check if this image name is already in use in the text widget
            try:
                self.text_area.index(image_id)
                # Name exists — check if it's a duplicate paste (same file, new position)
                # Use a numbered suffix to allow multiple instances
                counter = 2
                while True:
                    dup_id = f"img_{filename}#{counter}"
                    try:
                        self.text_area.index(dup_id)
                        counter += 1
                    except tk.TclError:
                        image_id = dup_id
                        break
            except tk.TclError:
                pass  # Name is free

            self.images[image_id] = photo

            # Insert image at specified position
            self.text_area.image_create(position, image=photo, name=image_id)

            # Add tag for image to enable click/right-click and resize
            # Get the index where image was inserted
            img_index = self.text_area.index(image_id)
            tag_name = f"imgtag_{filename}"
            self.text_area.tag_add(tag_name, img_index)

            # Bind resize events (check edge and drag)
            self.text_area.tag_bind(tag_name, "<Motion>", lambda e, fn=filename: self.on_image_motion(e, fn))
            self.text_area.tag_bind(tag_name, "<ButtonPress-1>", lambda e, fn=filename: self.on_image_press(e, fn))
            self.text_area.tag_bind(tag_name, "<B1-Motion>", lambda e, fn=filename: self.on_image_drag(e, fn))
            self.text_area.tag_bind(tag_name, "<ButtonRelease-1>", lambda e, fn=filename: self.on_image_release(e, fn))
            # Double-click to open image viewer
            self.text_area.tag_bind(tag_name, "<Double-Button-1>", lambda e, fn=filename: self.open_image_viewer(e, fn))
            # Right-click menu
            self.text_area.tag_bind(tag_name, "<Button-2>", lambda e: self.show_image_menu(e, filename))
            self.text_area.tag_bind(tag_name, "<Button-3>", lambda e: self.show_image_menu(e, filename))

            # Insert filename label below the image (if enabled)
            if self.show_image_name.get():
                if position == tk.INSERT:
                    self.text_area.insert(tk.INSERT, "\n")
                else:
                    # When loading (position is END), insert after the image
                    insert_pos = self.text_area.index(f"{img_index}+1c")
                    self.text_area.insert(insert_pos, "\n")
                    # Move cursor to after the newline for label insertion
                    self.text_area.mark_set(tk.INSERT, self.text_area.index(f"{insert_pos}+1c"))
                self.insert_image_label(filename)

        except Exception as e:
            print(f"Error inserting image: {e}")
            # Fallback: insert as text marker (preserve width if known)
            w = width or self.image_widths.get(filename)
            if w:
                self.text_area.insert(position, f"[IMAGE:{filename}:{w}]")
            else:
                self.text_area.insert(position, f"[IMAGE:{filename}]")

    def insert_image_label(self, internal_filename):
        """Insert image filename label at current cursor"""
        # Get display name (original filename or internal filename)
        display_name = self.get_display_name(internal_filename)

        # Insert filename (no icon for images)
        text_start = self.text_area.index(tk.INSERT)
        self.text_area.insert(tk.INSERT, display_name)
        text_end = self.text_area.index(tk.INSERT)

        # Add tag for text styling
        tag_name = f"imgname_{internal_filename}"
        self.text_area.tag_add(tag_name, text_start, text_end)
        self.text_area.tag_config(tag_name, foreground=self.current_theme_colors["fg_dim"])

        # Make name clickable
        self.text_area.tag_bind(tag_name, "<Button-1>", lambda e: self.copy_file_to_clipboard(internal_filename))
        self.text_area.tag_bind(tag_name, "<Button-2>", lambda e: self.show_image_menu(e, internal_filename))
        self.text_area.tag_bind(tag_name, "<Button-3>", lambda e: self.show_image_menu(e, internal_filename))
        self.text_area.tag_bind(tag_name, "<Enter>", lambda e: self.text_area.config(cursor="hand2"))
        self.text_area.tag_bind(tag_name, "<Leave>", lambda e: self.text_area.config(cursor=""))

    def show_image_menu(self, event, filename):
        """Show context menu for image"""
        menu = self.make_styled_menu()
        menu.add_command(label=self.tr("copy_link"), command=lambda: self.copy_internal_link("image", filename))
        menu.add_separator()
        menu.add_command(label=self.tr("copy_img_file"), command=lambda: self.copy_file_to_clipboard(filename))
        menu.add_command(label=self.tr("copy_file_path"), command=lambda: self.copy_file_path(filename))
        menu.add_command(label=self.tr("show_in_finder"), command=lambda: self.reveal_in_finder(filename))
        menu.add_command(label=self.tr("show_original"), command=lambda: self.reveal_original_file(filename))
        menu.add_command(label=self.tr("open_default"), command=lambda: self.open_file(filename))
        menu.add_separator()
        menu.add_command(label=self.tr("delete"), command=lambda: self.delete_attachment(filename, "image"))
        menu.tk_popup(event.x_root, event.y_root)

    def get_image_resize_edge(self, event, bbox):
        """Check which edge the mouse is near. Returns 'right', 'top', 'bottom', or None"""
        if not bbox:
            return None
        img_x, img_y, img_width, img_height = bbox
        edge_threshold = 25  # Increased for easier selection

        # Calculate distances to each edge
        dist_to_right = abs(event.x - (img_x + img_width))
        dist_to_bottom = abs(event.y - (img_y + img_height))
        dist_to_top = abs(event.y - img_y)

        # Check if mouse is within image bounds (with some tolerance)
        in_x_range = img_x - 10 <= event.x <= img_x + img_width + 10
        in_y_range = img_y - 10 <= event.y <= img_y + img_height + 10

        # Find the closest edge if within threshold
        edges = []
        if in_y_range and dist_to_right <= edge_threshold:
            edges.append(('right', dist_to_right))
        if in_x_range and dist_to_bottom <= edge_threshold:
            edges.append(('bottom', dist_to_bottom))
        if in_x_range and dist_to_top <= edge_threshold:
            edges.append(('top', dist_to_top))

        if not edges:
            return None

        # Return the closest edge
        edges.sort(key=lambda e: e[1])
        return edges[0][0]

    def on_image_motion(self, event, filename):
        """Check if mouse is near edges of the image for resize (throttled)"""
        # Throttle motion events to reduce CPU usage
        import time
        current_time = time.time() * 1000
        if current_time - self._last_motion_time < self._motion_throttle_ms:
            return  # Skip this event, too soon
        self._last_motion_time = current_time

        image_id = f"img_{filename}"
        try:
            bbox = self.text_area.bbox(image_id)
            if bbox:
                edge = self.get_image_resize_edge(event, bbox)
                if edge == 'right':
                    self.text_area.config(cursor="sb_h_double_arrow")
                elif edge in ('top', 'bottom'):
                    self.text_area.config(cursor="sb_v_double_arrow")
                else:
                    if self.image_resize_state is None:
                        self.text_area.config(cursor="")
        except:
            pass

    def on_image_press(self, event, filename):
        """Start resizing if mouse is near edge, otherwise schedule copy (may be cancelled by double-click)"""
        image_id = f"img_{filename}"
        try:
            bbox = self.text_area.bbox(image_id)
            if bbox:
                edge = self.get_image_resize_edge(event, bbox)
                if edge:
                    # Start resize
                    current_width = self.image_widths.get(filename, self.max_image_width)
                    x, y, width, height = bbox
                    self.image_resize_state = {
                        'filename': filename,
                        'start_x': event.x,
                        'start_y': event.y,
                        'start_width': current_width,
                        'start_height': height,
                        'image_id': image_id,
                        'edge': edge
                    }
                else:
                    # Schedule copy - will be cancelled if double-click occurs
                    # Cancel any pending click action
                    if hasattr(self, '_pending_click_id') and self._pending_click_id:
                        self.root.after_cancel(self._pending_click_id)
                    self._pending_click_id = self.root.after(300, lambda: self._do_image_click(filename))
        except:
            pass

    def _do_image_click(self, filename):
        """Execute delayed single-click action"""
        self._pending_click_id = None
        self.copy_file_to_clipboard(filename)

    def on_image_drag(self, event, filename):
        """Handle image resize drag"""
        if self.image_resize_state is None:
            return
        if self.image_resize_state['filename'] != filename:
            return

        edge = self.image_resize_state['edge']
        start_width = self.image_resize_state['start_width']
        start_height = self.image_resize_state['start_height']

        if edge == 'right':
            # Horizontal resize - calculate new width directly
            delta_x = event.x - self.image_resize_state['start_x']
            new_width = start_width + delta_x
        else:
            # Vertical resize (top or bottom) - calculate new width based on height change
            if edge == 'bottom':
                delta_y = event.y - self.image_resize_state['start_y']
            else:  # top
                delta_y = self.image_resize_state['start_y'] - event.y
            # Calculate new width maintaining aspect ratio
            new_height = start_height + delta_y
            ratio = new_height / start_height if start_height > 0 else 1
            new_width = int(start_width * ratio)

        # Clamp to valid range
        new_width = max(50, min(800, new_width))

        # Update the image in place
        self.resize_image_in_place(filename, new_width)

    def on_image_release(self, event, filename):
        """End resize and save the new size"""
        if self.image_resize_state is not None and self.image_resize_state['filename'] == filename:
            self.image_resize_state = None
            self.text_area.config(cursor="")

    def open_image_viewer(self, event, filename):
        """Open image viewer window with original size and zoom/pan support"""
        # Cancel any pending single-click action
        if hasattr(self, '_pending_click_id') and self._pending_click_id:
            self.root.after_cancel(self._pending_click_id)
            self._pending_click_id = None

        filepath = os.path.join(self.get_attachments_path(), filename)
        if not os.path.exists(filepath):
            return "break"

        try:
            # Load original image
            original_image = Image.open(filepath)

            # Create viewer window
            viewer = tk.Toplevel(self.root)
            viewer.title(f"{self.tr('img_viewer')} - {self.get_display_name(filename)}")

            # Set window size based on original image (with max screen limit)
            # Use main window position to determine which screen it's on
            root_x = self.root.winfo_x()
            root_y = self.root.winfo_y()
            root_w = self.root.winfo_width()
            root_h = self.root.winfo_height()
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            window_width = min(original_image.width + 40, screen_width - 100)
            window_height = min(original_image.height + 80, screen_height - 100)

            # Center on the main window's position (same screen)
            x = root_x + (root_w - window_width) // 2
            y = root_y + (root_h - window_height) // 2
            # Clamp to stay on screen
            x = max(0, x)
            y = max(0, y)
            viewer.geometry(f"{window_width}x{window_height}+{x}+{y}")

            t = self.current_theme_colors
            viewer.configure(bg=t["viewer_canvas"])

            # Create toolbar frame
            toolbar = tk.Frame(viewer, bg=t["viewer_toolbar"], height=36)
            toolbar.pack(side=tk.TOP, fill=tk.X)
            toolbar.pack_propagate(False)

            # Zoom label (will be updated)
            zoom_label = tk.Label(toolbar, text="100%", bg=t["viewer_toolbar"],
                                  fg=t["fg"], width=6, font=(SYSTEM_FONT, self.ui_font_size))
            zoom_label.pack(side=tk.LEFT, padx=(10, 5))

            # Create canvas for image display
            canvas = tk.Canvas(viewer, bg=t["viewer_canvas"], highlightthickness=0)
            canvas.pack(fill=tk.BOTH, expand=True)

            # Viewer state - define early so button callbacks can reference it
            state = {
                'original_image': original_image,
                'scale': 1.0,
                'photo': None,
                'image_id': None,
                'drag_x': 0,
                'drag_y': 0,
                'dragging': False
            }

            def update_image():
                """Update displayed image based on current scale"""
                scale = state['scale']
                new_width = max(1, int(original_image.width * scale))
                new_height = max(1, int(original_image.height * scale))

                if scale != 1.0:
                    scaled_image = original_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                else:
                    scaled_image = original_image

                photo = ImageTk.PhotoImage(scaled_image)
                state['photo'] = photo

                if state['image_id'] is None:
                    state['image_id'] = canvas.create_image(
                        window_width // 2, window_height // 2,
                        image=photo, anchor=tk.CENTER)
                else:
                    canvas.itemconfig(state['image_id'], image=photo)

                # Update zoom label
                zoom_label.config(text=f"{int(scale * 100)}%")

            def do_zoom(e, zoom_in):
                """Perform zoom operation"""
                # Get mouse position on canvas
                mouse_x = e.x
                mouse_y = e.y

                # Get current image position
                img_coords = canvas.coords(state['image_id'])
                if not img_coords:
                    return

                old_scale = state['scale']

                # Zoom in/out
                if zoom_in:
                    state['scale'] *= 1.25
                else:
                    state['scale'] /= 1.25

                # Limit scale range
                state['scale'] = max(0.1, min(10.0, state['scale']))

                # Calculate new position to zoom toward mouse
                scale_ratio = state['scale'] / old_scale
                new_x = mouse_x - (mouse_x - img_coords[0]) * scale_ratio
                new_y = mouse_y - (mouse_y - img_coords[1]) * scale_ratio

                update_image()
                canvas.coords(state['image_id'], new_x, new_y)

            def on_scroll(e):
                """Handle mouse wheel for zooming"""
                # macOS uses delta, Linux uses num
                if hasattr(e, 'delta') and e.delta != 0:
                    do_zoom(e, e.delta > 0)
                elif hasattr(e, 'num'):
                    do_zoom(e, e.num == 4)
                return "break"

            def on_key_zoom(e):
                """Handle keyboard zoom: +/= to zoom in, -/_ to zoom out"""
                # Create fake event with center coordinates
                class FakeEvent:
                    def __init__(self):
                        self.x = canvas.winfo_width() // 2
                        self.y = canvas.winfo_height() // 2
                fake_e = FakeEvent()

                if e.keysym in ('plus', 'equal'):
                    do_zoom(fake_e, True)
                elif e.keysym in ('minus', 'underscore'):
                    do_zoom(fake_e, False)
                elif e.keysym == '0':
                    # Reset to 100%
                    state['scale'] = 1.0
                    update_image()
                    canvas.coords(state['image_id'], canvas.winfo_width() // 2, canvas.winfo_height() // 2)

            def on_press(e):
                state['drag_x'] = e.x
                state['drag_y'] = e.y
                state['dragging'] = True
                canvas.config(cursor="fleur")

            def on_drag(e):
                if state['dragging'] and state['image_id']:
                    dx = e.x - state['drag_x']
                    dy = e.y - state['drag_y']
                    canvas.move(state['image_id'], dx, dy)
                    state['drag_x'] = e.x
                    state['drag_y'] = e.y

            def on_release(e):
                state['dragging'] = False
                canvas.config(cursor="")

            def btn_zoom_in():
                """Zoom in button callback"""
                state['scale'] *= 1.25
                state['scale'] = min(10.0, state['scale'])
                update_image()

            def btn_zoom_out():
                """Zoom out button callback"""
                state['scale'] /= 1.25
                state['scale'] = max(0.1, state['scale'])
                update_image()

            def btn_reset():
                """Reset zoom to 100%"""
                state['scale'] = 1.0
                update_image()
                # Re-center image
                viewer.update_idletasks()
                canvas.coords(state['image_id'], canvas.winfo_width() // 2, canvas.winfo_height() // 2)

            # Add zoom buttons using Labels (macOS ignores Button colors)
            def make_btn(parent, text, command, font_size=14):
                lbl = tk.Label(parent, text=text, bg=t["viewer_btn"], fg='white',
                              font=(SYSTEM_FONT, font_size, 'bold'), padx=12, pady=4, cursor='hand2')
                lbl.pack(side=tk.LEFT, padx=3)
                lbl.bind('<Button-1>', lambda e: command())
                lbl.bind('<Enter>', lambda e: lbl.config(bg=t["viewer_btn_hover"]))
                lbl.bind('<Leave>', lambda e: lbl.config(bg=t["viewer_btn"]))
                return lbl

            make_btn(toolbar, "  -  ", btn_zoom_out, 16)
            make_btn(toolbar, "  +  ", btn_zoom_in, 16)
            make_btn(toolbar, " 重置 ", btn_reset, 12)

            # Initial display
            update_image()

            # Bind mouse events for dragging
            canvas.bind("<ButtonPress-1>", on_press)
            canvas.bind("<B1-Motion>", on_drag)
            canvas.bind("<ButtonRelease-1>", on_release)

            # Bind scroll events to both canvas and viewer for better compatibility
            for widget in [canvas, viewer]:
                widget.bind("<MouseWheel>", on_scroll)  # Windows/macOS
                widget.bind("<Button-4>", on_scroll)    # Linux scroll up
                widget.bind("<Button-5>", on_scroll)    # Linux scroll down

            # Make canvas focusable and grab focus on enter
            canvas.configure(takefocus=True)
            canvas.bind("<Enter>", lambda e: canvas.focus_set())

            # Keyboard shortcuts
            viewer.bind("<Escape>", lambda e: viewer.destroy())
            viewer.bind("<plus>", on_key_zoom)
            viewer.bind("<equal>", on_key_zoom)
            viewer.bind("<minus>", on_key_zoom)
            viewer.bind("<Key-0>", on_key_zoom)
            # Cmd/Ctrl + plus/minus for zoom
            viewer.bind("<Command-equal>", on_key_zoom)
            viewer.bind("<Command-minus>", on_key_zoom)
            viewer.bind("<Command-0>", on_key_zoom)

            # Focus the canvas to receive scroll events
            canvas.focus_set()

        except Exception as e:
            print(f"Error opening image viewer: {e}")

        # Prevent the double-click from triggering single-click action
        return "break"

    def resize_image_in_place(self, filename, new_width):
        """Resize image and replace it in text area without changing position"""
        image_id = f"img_{filename}"
        filepath = os.path.join(self.get_attachments_path(), filename)

        if not os.path.exists(filepath):
            return

        try:
            # Get current image position
            img_index = self.text_area.index(image_id)

            # Load and resize image
            image = Image.open(filepath)
            ratio = new_width / image.width
            new_height = int(image.height * ratio)
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(image)

            # Update stored reference
            self.images[image_id] = photo
            self.image_widths[filename] = new_width

            # Update the image in the text area
            self.text_area.image_configure(image_id, image=photo)

            # Mark content as modified so it will be saved
            self.content_modified = True

        except Exception as e:
            print(f"Error resizing image: {e}")

    def _insert_video_preview(self, internal_filename, position):
        """Insert video thumbnail preview at position. Returns True on success, False to fall back to emoji."""
        if not PIL_AVAILABLE:
            return False

        vidthumb_id = f"vidthumb_{internal_filename}"

        # Deferred mode: insert placeholder, queue for later
        if getattr(self, '_fast_load_mode', False) and vidthumb_id not in self.images:
            try:
                if not hasattr(self, '_placeholder_photo'):
                    self._placeholder_photo = ImageTk.PhotoImage(
                        Image.new('RGBA', (1, 1), (0, 0, 0, 0)))
                self.images[vidthumb_id] = self._placeholder_photo
                self.text_area.image_create(position, image=self._placeholder_photo, name=vidthumb_id)

                icon_tag = f"icon_{internal_filename}"
                img_index = self.text_area.index(vidthumb_id)
                self.text_area.tag_add(icon_tag, img_index)

                display_name = self.get_display_name(internal_filename)
                if position == tk.END:
                    self.text_area.insert(tk.END, "\n")
                    text_start = self.text_area.index(tk.END + "-1c")
                    self.text_area.insert(tk.END, display_name)
                    text_end = self.text_area.index(tk.END + "-1c")
                else:
                    self.text_area.insert(tk.INSERT, "\n")
                    text_start = self.text_area.index(tk.INSERT)
                    self.text_area.insert(tk.INSERT, display_name + "\n")
                    text_end = self.text_area.index(tk.INSERT + "-1c")

                tag_name = f"file_{internal_filename}"
                self.text_area.tag_add(tag_name, text_start, text_end)
                self.text_area.tag_config(tag_name, foreground=self.current_theme_colors["accent_green"], underline=False)

                # Queue for deferred loading (marked as video)
                self._deferred_images.append(('__video__', internal_filename, None))
                return True
            except Exception:
                return False

        # Fast path: reuse existing PhotoImage (during undo/redo)
        if vidthumb_id in self.images:
            photo = self.images[vidthumb_id]
        else:
            thumb = self._get_video_thumbnail(internal_filename)
            if thumb is None:
                return False

            # Resize thumbnail to fit
            target_width = min(self.max_image_width, 400)
            target_width = max(50, min(800, target_width))
            if thumb.width != target_width:
                ratio = target_width / thumb.width
                new_height = int(thumb.height * ratio)
                thumb = thumb.resize((target_width, new_height), Image.Resampling.LANCZOS)

            photo = ImageTk.PhotoImage(thumb)
            self.images[vidthumb_id] = photo

        try:
            display_name = self.get_display_name(internal_filename)

            # Insert the thumbnail image
            self.text_area.image_create(position, image=photo, name=vidthumb_id)

            # Tag the image position with icon_{filename} for serialization compatibility
            icon_tag = f"icon_{internal_filename}"
            img_index = self.text_area.index(vidthumb_id)
            self.text_area.tag_add(icon_tag, img_index)

            # Insert newline + filename text
            if position == tk.END:
                self.text_area.insert(tk.END, "\n")
                text_start = self.text_area.index(tk.END + "-1c")
                self.text_area.insert(tk.END, display_name)
                text_end = self.text_area.index(tk.END + "-1c")
            else:
                self.text_area.insert(tk.INSERT, "\n")
                text_start = self.text_area.index(tk.INSERT)
                self.text_area.insert(tk.INSERT, display_name + "\n")
                text_end = self.text_area.index(tk.INSERT + "-1c")

            # Tag filename text
            tag_name = f"file_{internal_filename}"
            self.text_area.tag_add(tag_name, text_start, text_end)
            self.text_area.tag_config(tag_name, foreground=self.current_theme_colors["accent_green"], underline=False)

            # Bind click handlers on thumbnail image — single click opens video
            self.text_area.tag_bind(icon_tag, "<Button-1>", lambda e: self.open_file(internal_filename))
            self.text_area.tag_bind(icon_tag, "<Button-2>", lambda e: self.show_file_menu(e, internal_filename))
            self.text_area.tag_bind(icon_tag, "<Button-3>", lambda e: self.show_file_menu(e, internal_filename))
            self.text_area.tag_bind(icon_tag, "<Enter>", lambda e: self.text_area.config(cursor="hand2"))
            self.text_area.tag_bind(icon_tag, "<Leave>", lambda e: self.text_area.config(cursor=""))

            # Bind click handlers on filename text
            self.text_area.tag_bind(tag_name, "<Button-1>", lambda e: self.select_file(internal_filename))
            self.text_area.tag_bind(tag_name, "<Double-Button-1>", lambda e: self.open_file(internal_filename))
            self.text_area.tag_bind(tag_name, "<Button-2>", lambda e: self.show_file_menu(e, internal_filename))
            self.text_area.tag_bind(tag_name, "<Button-3>", lambda e: self.show_file_menu(e, internal_filename))
            self.text_area.tag_bind(tag_name, "<Enter>", lambda e: self.text_area.config(cursor="hand2"))
            self.text_area.tag_bind(tag_name, "<Leave>", lambda e: self.text_area.config(cursor=""))

            return True

        except Exception as e:
            print(f"Error inserting video preview: {e}")
            return False

    def insert_file_link(self, internal_filename):
        """Insert file link at cursor position"""
        # Try video thumbnail preview first
        if self._is_video_file(internal_filename):
            if self._insert_video_preview(internal_filename, position=tk.INSERT):
                return

        # Get display name (original filename)
        display_name = self.get_display_name(internal_filename)
        # Get file icon
        icon = self.get_file_icon(display_name)

        # Insert icon with larger font
        icon_start = self.text_area.index(tk.INSERT)
        self.text_area.insert(tk.INSERT, icon)
        icon_end = self.text_area.index(tk.INSERT)

        # Tag for icon with larger font
        icon_tag = f"icon_{internal_filename}"
        self.text_area.tag_add(icon_tag, icon_start, icon_end)
        self.text_area.tag_config(icon_tag, font=(SYSTEM_FONT, self.icon_font_size))

        # Insert space and filename
        self.text_area.insert(tk.INSERT, " ")
        text_start = self.text_area.index(tk.INSERT)
        self.text_area.insert(tk.INSERT, display_name + "\n")
        text_end = self.text_area.index(tk.INSERT + "-1c")

        # Add tag for text styling and click handling
        tag_name = f"file_{internal_filename}"
        self.text_area.tag_add(tag_name, text_start, text_end)
        self.text_area.tag_config(tag_name, foreground=self.current_theme_colors["accent_green"], underline=False)

        # Also make icon clickable
        self.text_area.tag_bind(icon_tag, "<Button-1>", lambda e: self.select_file(internal_filename))
        self.text_area.tag_bind(icon_tag, "<Double-Button-1>", lambda e: self.open_file(internal_filename))
        self.text_area.tag_bind(icon_tag, "<Button-2>", lambda e: self.show_file_menu(e, internal_filename))
        self.text_area.tag_bind(icon_tag, "<Button-3>", lambda e: self.show_file_menu(e, internal_filename))
        self.text_area.tag_bind(icon_tag, "<Enter>", lambda e: self.text_area.config(cursor="hand2"))
        self.text_area.tag_bind(icon_tag, "<Leave>", lambda e: self.text_area.config(cursor=""))
        # Single click to select file (for copy)
        self.text_area.tag_bind(tag_name, "<Button-1>", lambda e: self.select_file(internal_filename))
        # Double-click to open file
        self.text_area.tag_bind(tag_name, "<Double-Button-1>", lambda e: self.open_file(internal_filename))
        # Right-click to show context menu
        self.text_area.tag_bind(tag_name, "<Button-2>", lambda e: self.show_file_menu(e, internal_filename))  # macOS
        self.text_area.tag_bind(tag_name, "<Button-3>", lambda e: self.show_file_menu(e, internal_filename))  # Windows/Linux
        self.text_area.tag_bind(tag_name, "<Enter>", lambda e: self.text_area.config(cursor="hand2"))
        self.text_area.tag_bind(tag_name, "<Leave>", lambda e: self.text_area.config(cursor=""))

    def select_file(self, filename):
        """Select file and copy to clipboard immediately"""
        self.selected_file = filename
        # Copy file to clipboard immediately on click
        self.copy_file_to_clipboard(filename)

    def show_file_menu(self, event, filename):
        """Show context menu for file link"""
        menu = self.make_styled_menu()
        menu.add_command(label=self.tr("copy_link"), command=lambda: self.copy_internal_link("file", filename))
        menu.add_separator()
        menu.add_command(label=self.tr("open_file"), command=lambda: self.open_file(filename))
        menu.add_command(label=self.tr("copy_file"), command=lambda: self.copy_file_to_clipboard(filename))
        menu.add_command(label=self.tr("copy_file_path"), command=lambda: self.copy_file_path(filename))
        menu.add_command(label=self.tr("show_in_finder"), command=lambda: self.reveal_in_finder(filename))
        menu.add_command(label=self.tr("show_original"), command=lambda: self.reveal_original_file(filename))
        menu.add_separator()
        menu.add_command(label=self.tr("delete"), command=lambda: self.delete_attachment(filename, "file"))
        menu.tk_popup(event.x_root, event.y_root)

    def delete_attachment(self, filename, attachment_type):
        """Delete image or file from the note (removes from text area only, file remains in attachments)"""
        try:
            if attachment_type == "image":
                # Delete image from text area
                image_id = f"img_{filename}"
                try:
                    img_index = self.text_area.index(image_id)
                    # Delete the image
                    self.text_area.delete(img_index)
                    # Remove from references
                    if image_id in self.images:
                        del self.images[image_id]
                    if filename in self.image_widths:
                        del self.image_widths[filename]
                except tk.TclError:
                    pass  # Image not found

                # Delete associated image name label if exists
                name_tag = f"imgname_{filename}"
                try:
                    ranges = self.text_area.tag_ranges(name_tag)
                    if ranges:
                        # Also delete the newline before the label
                        start = str(ranges[0])
                        end = str(ranges[1])
                        prev_char = self.text_area.get(f"{start}-1c")
                        if prev_char == "\n":
                            start = f"{start}-1c"
                        self.text_area.delete(start, end)
                except tk.TclError:
                    pass
            else:
                # Delete file link from text area
                icon_tag = f"icon_{filename}"
                file_tag = f"file_{filename}"

                # Remove video thumbnail image if present
                vidthumb_id = f"vidthumb_{filename}"
                try:
                    self.text_area.index(vidthumb_id)
                    self.text_area.delete(self.text_area.index(vidthumb_id))
                    if vidthumb_id in self.images:
                        del self.images[vidthumb_id]
                except tk.TclError:
                    pass

                try:
                    # Get the range of icon and file text
                    icon_ranges = self.text_area.tag_ranges(icon_tag)
                    file_ranges = self.text_area.tag_ranges(file_tag)
                    if icon_ranges and file_ranges:
                        # Delete from icon start to file text end (including the space between)
                        start = str(icon_ranges[0])
                        end = str(file_ranges[1])
                        # Check if there's a newline after
                        next_char = self.text_area.get(end)
                        if next_char == "\n":
                            end = f"{end}+1c"
                        self.text_area.delete(start, end)
                    elif file_ranges:
                        # Video preview: thumbnail was deleted above, clean up filename text
                        start = str(file_ranges[0])
                        end = str(file_ranges[1])
                        # Also delete the newline before filename
                        prev_char = self.text_area.get(f"{start}-1c")
                        if prev_char == "\n":
                            start = f"{start}-1c"
                        next_char = self.text_area.get(end)
                        if next_char == "\n":
                            end = f"{end}+1c"
                        self.text_area.delete(start, end)
                except tk.TclError:
                    pass

                # Clean up cached video thumbnail
                thumb_cache = os.path.join(self.get_attachments_path(), f"_thumb_{filename}.png")
                if os.path.exists(thumb_cache):
                    try:
                        os.remove(thumb_cache)
                    except Exception:
                        pass

            # Mark content as modified
            self.content_modified = True

        except Exception as e:
            print(f"Error deleting attachment: {e}")

    def copy_internal_link(self, link_type, internal_filename):
        """Copy file/image link for internal paste within the board"""
        self.copied_internal_link = (link_type, internal_filename)
        # Also clear system clipboard to indicate internal copy
        self.root.clipboard_clear()
        # Put a marker in clipboard so we know it's an internal link
        self.root.clipboard_append(f"[INTERNAL:{link_type}:{internal_filename}]")

    def copy_file_to_clipboard(self, internal_filename, internal_marker=None):
        """Copy the actual file to clipboard so it can be pasted in Finder and other apps

        Args:
            internal_filename: The internal filename to copy
            internal_marker: Optional marker string to also set in text clipboard for internal paste detection
        """
        filepath = os.path.abspath(os.path.join(self.get_attachments_path(), internal_filename))
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            return

        # Get original filename
        original_name = self.get_display_name(internal_filename)

        # Check if it's an image file
        image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp'}
        _, ext = os.path.splitext(filepath)
        is_image = ext.lower() in image_extensions

        # Create temp directory for the copy with original name
        import tempfile
        temp_dir = tempfile.mkdtemp()
        temp_filepath = os.path.join(temp_dir, original_name)

        try:
            # Copy file or directory with original name to temp location
            if os.path.isdir(filepath):
                shutil.copytree(filepath, temp_filepath)
            else:
                shutil.copy2(filepath, temp_filepath)
            copy_path = temp_filepath
        except Exception as e:
            print(f"Error creating temp copy: {e}")
            copy_path = filepath  # Fallback to internal name

        if platform.system() == "Darwin":
            try:
                # Escape the marker string for AppleScript
                marker_escaped = internal_marker.replace('\\', '\\\\').replace('"', '\\"') if internal_marker else ""

                if is_image:
                    # For images: copy both file URL and image data (for web/app paste)
                    if internal_marker:
                        script = f'''
                        use framework "AppKit"
                        use framework "Foundation"

                        set thePath to "{copy_path}"
                        set theURL to current application's NSURL's fileURLWithPath:thePath
                        set theImage to current application's NSImage's alloc()'s initWithContentsOfFile:thePath
                        set theMarker to "{marker_escaped}"

                        set thePasteboard to current application's NSPasteboard's generalPasteboard()
                        thePasteboard's clearContents()

                        if theImage is not missing value then
                            -- Write image, file URL, and text marker for internal paste detection
                            thePasteboard's writeObjects:{{theImage, theURL}}
                        else
                            thePasteboard's writeObjects:{{theURL}}
                        end if

                        -- Also set string type for internal marker detection
                        thePasteboard's setString:theMarker forType:(current application's NSPasteboardTypeString)
                        '''
                    else:
                        script = f'''
                        use framework "AppKit"
                        use framework "Foundation"

                        set thePath to "{copy_path}"
                        set theURL to current application's NSURL's fileURLWithPath:thePath
                        set theImage to current application's NSImage's alloc()'s initWithContentsOfFile:thePath

                        set thePasteboard to current application's NSPasteboard's generalPasteboard()
                        thePasteboard's clearContents()

                        if theImage is not missing value then
                            -- Write both image and file URL for maximum compatibility
                            thePasteboard's writeObjects:{{theImage, theURL}}
                        else
                            thePasteboard's writeObjects:{{theURL}}
                        end if
                        '''
                else:
                    # For non-image files: just copy file URL
                    if internal_marker:
                        script = f'''
                        use framework "AppKit"
                        set thePath to "{copy_path}"
                        set theURL to current application's NSURL's fileURLWithPath:thePath
                        set theMarker to "{marker_escaped}"
                        set thePasteboard to current application's NSPasteboard's generalPasteboard()
                        thePasteboard's clearContents()
                        thePasteboard's writeObjects:{{theURL}}
                        -- Also set string type for internal marker detection
                        thePasteboard's setString:theMarker forType:(current application's NSPasteboardTypeString)
                        '''
                    else:
                        script = f'''
                        use framework "AppKit"
                        set thePath to "{copy_path}"
                        set theURL to current application's NSURL's fileURLWithPath:thePath
                        set thePasteboard to current application's NSPasteboard's generalPasteboard()
                        thePasteboard's clearContents()
                        thePasteboard's writeObjects:{{theURL}}
                        '''

                result = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    print(f"File copied to clipboard: {original_name}")
                else:
                    print(f"AppleScript error: {result.stderr}")
            except Exception as e:
                print(f"Error copying file to clipboard: {e}")
        elif platform.system() == "Windows":
            try:
                ps_script = f'Set-Clipboard -Path "{copy_path}"'
                subprocess.run(["powershell", "-Command", ps_script], check=True)
                # For Windows, set internal marker using tkinter after file copy
                if internal_marker:
                    self.root.clipboard_append(internal_marker)
            except Exception as e:
                print(f"Error copying file to clipboard: {e}")

    def copy_file_path(self, filename):
        """Copy file path to clipboard"""
        filepath = os.path.abspath(os.path.join(self.get_attachments_path(), filename))
        self.root.clipboard_clear()
        self.root.clipboard_append(filepath)

    def reveal_in_finder(self, filename):
        """Reveal file in Finder/Explorer"""
        filepath = os.path.abspath(os.path.join(self.get_attachments_path(), filename))
        if os.path.exists(filepath):
            try:
                if platform.system() == "Darwin":  # macOS
                    subprocess.run(["open", "-R", filepath])
                elif platform.system() == "Windows":
                    subprocess.run(["explorer", "/select,", filepath])
                else:  # Linux
                    subprocess.run(["xdg-open", os.path.dirname(filepath)])
            except Exception as e:
                print(f"Error revealing file: {e}")

    def reveal_original_file(self, internal_filename):
        """Reveal the original source file location"""
        original_path = self.get_original_path(internal_filename)

        if not original_path:
            print(f"Original path not recorded for: {internal_filename}")
            return

        if os.path.exists(original_path):
            try:
                if platform.system() == "Darwin":  # macOS
                    subprocess.run(["open", "-R", original_path])
                elif platform.system() == "Windows":
                    subprocess.run(["explorer", "/select,", original_path])
                else:  # Linux
                    subprocess.run(["xdg-open", os.path.dirname(original_path)])
            except Exception as e:
                print(f"Error revealing original file: {e}")
        else:
            # File moved/deleted, open the original folder if exists
            original_dir = os.path.dirname(original_path)
            if os.path.exists(original_dir):
                try:
                    if platform.system() == "Darwin":
                        subprocess.run(["open", original_dir])
                    elif platform.system() == "Windows":
                        subprocess.run(["explorer", original_dir])
                    else:
                        subprocess.run(["xdg-open", original_dir])
                except Exception as e:
                    print(f"Error opening original folder: {e}")
            else:
                print(f"Original file no longer exists: {original_path}")

    def open_file(self, filename):
        """Open file with default system application"""
        filepath = os.path.join(self.get_attachments_path(), filename)
        if os.path.exists(filepath):
            try:
                if platform.system() == "Darwin":  # macOS
                    subprocess.run(["open", filepath])
                elif platform.system() == "Windows":
                    os.startfile(filepath)
                else:  # Linux
                    subprocess.run(["xdg-open", filepath])
            except Exception as e:
                print(f"Error opening file: {e}")

    def insert_text_with_urls(self, text, position=tk.END):
        """Insert text at END and make URLs clickable with Alt/Cmd+Click (for loading)"""
        # If no URLs, just insert text normally
        if not self.url_pattern.search(text):
            self.text_area.insert(position, text)
            return

        # Find all URLs in the text
        last_end = 0
        for match in self.url_pattern.finditer(text):
            # Insert text before URL
            if match.start() > last_end:
                self.text_area.insert(tk.END, text[last_end:match.start()])

            # Insert URL with tag
            url = match.group(1)
            # Get position BEFORE inserting
            url_start = self.text_area.index("end-1c")
            self.text_area.insert(tk.END, url)
            # Get position AFTER inserting
            url_end = self.text_area.index("end-1c")

            # Create and configure URL tag
            self.create_url_tag(url, url_start, url_end)

            last_end = match.end()

        # Insert remaining text after last URL
        if last_end < len(text):
            self.text_area.insert(tk.END, text[last_end:])

    def insert_text_with_urls_at_cursor(self, text):
        """Insert text at cursor position and make URLs clickable"""
        # Find all URLs in the text
        last_end = 0
        for match in self.url_pattern.finditer(text):
            # Insert text before URL
            if match.start() > last_end:
                self.text_area.insert(tk.INSERT, text[last_end:match.start()])

            # Insert URL with tag
            url = match.group(1)
            # Get position BEFORE inserting
            url_start = self.text_area.index(tk.INSERT)
            self.text_area.insert(tk.INSERT, url)
            # Get position AFTER inserting
            url_end = self.text_area.index(tk.INSERT)

            # Create and configure URL tag
            self.create_url_tag(url, url_start, url_end)

            last_end = match.end()

        # Insert remaining text after last URL
        if last_end < len(text):
            self.text_area.insert(tk.INSERT, text[last_end:])

    def create_url_tag(self, url, url_start, url_end):
        """Create a clickable URL tag"""
        # Create unique tag for this URL
        tag_name = f"url_{len(self.url_tags)}"
        self.url_tags.add(tag_name)
        self.text_area.tag_add(tag_name, url_start, url_end)
        self.text_area.tag_config(tag_name, foreground=self.current_theme_colors["accent_url"], underline=False)

        # Bind Alt/Option/Cmd+Click to open URL
        self.text_area.tag_bind(tag_name, "<Alt-Button-1>", lambda e, u=url: self.open_url(u))
        self.text_area.tag_bind(tag_name, "<Option-Button-1>", lambda e, u=url: self.open_url(u))
        self.text_area.tag_bind(tag_name, "<Command-Button-1>", lambda e, u=url: self.open_url(u))
        self.text_area.tag_bind(tag_name, "<Control-Button-1>", lambda e, u=url: self.open_url(u))
        # Show hand cursor when hovering
        self.text_area.tag_bind(tag_name, "<Enter>", lambda e, t=tag_name: self.on_url_enter(t))
        self.text_area.tag_bind(tag_name, "<Leave>", lambda e: self.text_area.config(cursor=""))

        # URL title preview: fetch async if not cached (deferred insertion handled by caller)
        if url not in self._url_title_cache:
            self._fetch_url_title_async(url)

        return tag_name

    def _fetch_url_title(self, url):
        """Synchronously fetch the <title> of a URL. Returns title string or None."""
        try:
            import gzip
            import zlib
            from urllib.parse import urlparse
            original_host = urlparse(url).hostname

            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type and "application/xhtml" not in content_type:
                    return None

                # Detect auth/login redirects (redirected to a different host with login-like path)
                final_host = urlparse(resp.url).hostname
                final_path = urlparse(resp.url).path.lower()
                is_login_redirect = (
                    final_host != original_host and
                    any(kw in final_path for kw in ("/login", "/signin", "/auth", "/accounts", "/sso"))
                )

                # Read first 48KB — some sites have large heads (e.g. GitHub > 22KB)
                data = resp.read(49152)

                # Decompress if gzip/deflate encoded (handle truncated streams)
                encoding = resp.headers.get("Content-Encoding", "").lower()
                if encoding == "gzip":
                    try:
                        data = gzip.decompress(data)
                    except EOFError:
                        # Truncated gzip — use zlib with gzip wrapper flag
                        dec = zlib.decompressobj(zlib.MAX_WBITS | 16)
                        data = dec.decompress(data)
                elif encoding == "deflate":
                    try:
                        data = zlib.decompress(data, -zlib.MAX_WBITS)
                    except zlib.error:
                        data = zlib.decompress(data)

                charset = "utf-8"
                if "charset=" in content_type:
                    charset = content_type.split("charset=")[-1].split(";")[0].strip()
                text = data.decode(charset, errors="replace")

                title = None
                # Try <title> tag first
                m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
                if m:
                    title = html.unescape(m.group(1)).strip()
                    title = re.sub(r"\s+", " ", title)

                # Fallback: og:title or twitter:title meta tags
                if not title:
                    m = re.search(
                        r'<meta\s+(?:property|name)=["\'](?:og:title|twitter:title)["\']\s+content=["\']([^"\']+)["\']',
                        text, re.IGNORECASE
                    )
                    if not m:
                        # Also try content-first order
                        m = re.search(
                            r'<meta\s+content=["\']([^"\']+)["\']\s+(?:property|name)=["\'](?:og:title|twitter:title)["\']',
                            text, re.IGNORECASE
                        )
                    if m:
                        title = html.unescape(m.group(1)).strip()
                        title = re.sub(r"\s+", " ", title)

                # If redirected to login page, ignore the login page title
                if is_login_redirect:
                    # Use the original domain name as a fallback hint
                    domain = original_host.replace("www.", "")
                    return domain

                if not title:
                    return None

                if len(title) > 50:
                    title = title[:50] + "…"
                return title
        except Exception:
            pass
        return None

    def _fetch_url_title_async(self, url):
        """Spawn a background thread to fetch the URL title, then trigger markdown update."""
        if url in self._url_fetch_pending:
            return
        self._url_fetch_pending.add(url)

        def _worker():
            title = self._fetch_url_title(url)
            self._url_fetch_pending.discard(url)
            if title:
                self._url_title_cache[url] = title
                self._save_url_title_cache()
                # Schedule a markdown update to pick up the cached title
                try:
                    self.root.after(0, self._schedule_markdown_update)
                except Exception:
                    pass

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _insert_url_preview(self, url, title, tag_name):
        """Insert title text on a new line right after the URL.
        Using a leading newline keeps the URL on its own line so users can
        triple-click / copy the URL line without picking up the title."""
        ta = self.text_area
        # Find the end position of the URL tag
        ranges = ta.tag_ranges(tag_name)
        if not ranges:
            return
        url_end = str(ranges[-1])

        # Skip if a preview already exists right after this URL (any
        # url_preview-tagged text immediately following the URL).
        try:
            tags_at = ta.tag_names(url_end)
            if any(t.startswith("url_preview") for t in tags_at):
                return
        except Exception:
            return

        # Newline-prefixed preview keeps the URL line clean for copy operations.
        preview_text = f"\n  {title}"
        preview_tag = f"url_preview_{len(self._url_preview_tags)}"
        self._url_preview_tags.add(preview_tag)

        # Insert without polluting undo stack
        ta.config(undo=False)
        try:
            ta.insert(url_end, preview_text, (preview_tag, "url_preview"))
        finally:
            ta.config(undo=True)

    def _remove_all_url_previews(self):
        """Remove all URL preview text from the text area."""
        ta = self.text_area
        ta.config(undo=False)
        try:
            for tag in list(self._url_preview_tags):
                ranges = ta.tag_ranges(tag)
                # Delete in reverse order to keep indices valid
                pairs = []
                for i in range(0, len(ranges), 2):
                    pairs.append((str(ranges[i]), str(ranges[i + 1])))
                for start, end in reversed(pairs):
                    ta.delete(start, end)
                ta.tag_delete(tag)
            self._url_preview_tags.clear()
            # Also clean up any orphaned url_preview-tagged text
            ranges = ta.tag_ranges("url_preview")
            pairs = []
            for i in range(0, len(ranges), 2):
                pairs.append((str(ranges[i]), str(ranges[i + 1])))
            for start, end in reversed(pairs):
                ta.delete(start, end)
        finally:
            ta.config(undo=True)

    def on_url_enter(self, tag_name):
        """Show tooltip hint for URL"""
        # Change cursor to hand on hover (user can then Alt/Cmd+Click)
        self.text_area.config(cursor="hand2")

    def open_url(self, url):
        """Open URL in default browser"""
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"Error opening URL: {e}")
        return "break"

if __name__ == "__main__":
    root = tk.Tk()
    app = NoteApp(root)
    root.mainloop()
