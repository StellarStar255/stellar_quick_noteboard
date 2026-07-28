"""Internationalisation (i18n) — no GUI imports.

Each key maps to (Chinese, English).  Use Translator.tr(key) at runtime.
"""

I18N = {
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
    "import_err":       ("导入失败: {}", "Import failed: {}"),
    "search_placeholder": ("搜索...", "Search..."),
    "search_n_of_m":    ("{}/{}", "{}/{}"),
    # Text context menu
    "ctx_cut":          ("剪切", "Cut"),
    "ctx_copy":         ("复制", "Copy"),
    "ctx_paste":        ("粘贴", "Paste"),
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
    "no_delete_last":   ("不能删除最后一个笔记本", "Cannot delete the last notebook"),
    "nb_exists":        ("笔记本已存在", "Notebook already exists"),
    "confirm_del_msg":  ("确定要删除笔记本 '{}' 吗？\n这将删除所有笔记和附件！",
                         "Delete notebook '{}'?\nAll notes and attachments will be lost!"),
    "quit_confirm_title": ("退出确认", "Confirm Quit"),
    "quit_confirm_msg":   ("确定要退出 Quick Note Board 吗？", "Quit Quick Note Board?"),
    # Language toggle button
    "lang_toggle":      ("EN", "中"),
    # Save failure notification
    "save_failed_msg":  ("保存笔记本 '{}' 失败：\n{}\n\n请检查磁盘空间和文件权限。",
                         "Failed to save notebook '{}':\n{}\n\nCheck disk space and file permissions."),
    # Find & replace
    "replace_placeholder": ("替换为...", "Replace with..."),
    "replace_btn":      ("替换", "Replace"),
    "replace_all_btn":  ("全部替换", "Replace All"),
    "replaced_n":       ("已替换 {} 处", "Replaced {}"),
    # Global (cross-notebook) search
    "global_search":    ("全局搜索...", "Search All Notebooks…"),
    "global_search_title": ("全局搜索", "Global Search"),
    "global_search_hint":  ("搜索所有笔记本...", "Search all notebooks..."),
    "global_results_n": ("{} 个结果", "{} results"),
    # Backup restore
    "restore_backup":   ("恢复备份...", "Restore Backup…"),
    "restore_title":    ("恢复备份 - {}", "Restore Backup - {}"),
    "restore_btn":      ("恢复此备份", "Restore This Backup"),
    "no_backups":       ("当前笔记本没有可用的备份", "No backups available for this notebook"),
    "restore_confirm_msg": ("确定用该备份覆盖当前内容吗？\n当前内容会先自动备份一份。",
                            "Replace current content with this backup?\nCurrent content will be backed up first."),
    # Export formats
    "export_md":        ("导出为 Markdown...", "Export as Markdown…"),
    "export_html":      ("导出为 HTML...", "Export as HTML…"),
    # Word count status bar
    "wc_stats":         ("字数 {}  ·  字符 {}", "{} words  ·  {} chars"),
    "wc_stats_sel":     ("选中：字数 {}  ·  字符 {}", "Selected: {} words  ·  {} chars"),
    # Software update
    "check_update":     ("检查更新... (当前 v{})", "Check for Updates… (v{})"),
    "update_title":     ("软件更新", "Software Update"),
    "update_available": ("发现新版本 v{}（当前 v{}）。\n是否下载并升级？",
                         "Version v{} is available (you have v{}).\nDownload and upgrade now?"),
    "update_none":      ("当前已是最新版本（v{}）。", "You are up to date (v{})."),
    "update_downloading": ("正在下载更新...", "Downloading update…"),
    "update_ready_msg": ("安装包已开始安装。\n本应用即将退出，请按安装程序提示完成升级。",
                         "The installer has been launched.\nThis app will now quit — follow the installer to finish upgrading."),
    "update_failed":    ("检查更新失败：{}\n\n也可以到发布页手动下载。",
                         "Update check failed: {}\n\nYou can also download manually from the releases page."),
    "update_no_asset":  ("新版本 v{} 暂无适用于当前系统的安装包，\n是否打开发布页手动下载？",
                         "v{} has no installer for this platform yet.\nOpen the releases page to download manually?"),
    "update_auto_msg":  ("升级将自动完成：应用即将退出，安装后自动重启到新版本。",
                         "The update installs automatically: the app will now quit and relaunch on the new version."),
    # Menu bar & system tray (v2 additions)
    "help_menu":        ("帮助", "Help"),
    "tray_show":        ("显示主窗口", "Show Window"),
    "tray_quit":        ("退出", "Quit"),
}


class Translator:
    """Resolve i18n keys to the active language.

    Mirrors NoteApp.tr() from v1: index 0 = Chinese, 1 = English, with a
    (key, key) fallback so a missing key degrades gracefully.
    """

    def __init__(self, language="zh"):
        self.language = language

    def tr(self, key):
        return I18N.get(key, (key, key))[0 if self.language == "zh" else 1]

    def toggle(self):
        self.language = "en" if self.language == "zh" else "zh"
        return self.language
