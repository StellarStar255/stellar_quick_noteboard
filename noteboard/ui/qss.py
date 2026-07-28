"""Build the application-wide Qt style sheet from a THEMES palette.

One QSS string covers every shell widget (toolbar, sidebar, menus,
scrollbars, dialogs, status bar…), approximating the v1 ttk look: flat
chip buttons with hover/pressed states, hairline borders, accent focus
rings. The main window applies it with setStyleSheet() so all children
(including parented dialogs and menus) inherit it.
"""

from noteboard.core.theme import blend


def build_qss(t, ui_font_size, font_family):
    """QSS for theme palette *t* (a THEMES[...] dict)."""
    fs = int(ui_font_size)
    small = max(10, fs - 3)
    accent_hover = blend(t["accent"], "#ffffff", 0.18)
    return f"""
QWidget {{
    background-color: {t["bg"]};
    color: {t["fg"]};
    font-family: "{font_family}";
    font-size: {fs}pt;
}}

/* ── Toolbar ─────────────────────────────────────────────────────── */
QToolBar {{
    background-color: {t["bg"]};
    border: none;
    padding: 3px 5px;
    spacing: 3px;
}}
QToolBar::separator {{
    background-color: {t["separator"]};
    width: 1px;
    margin: 3px 5px;
}}
QToolButton {{
    background-color: {t["button_bg"]};
    color: {t["button_fg"]};
    border: 1px solid {t["border"]};
    border-radius: 4px;
    padding: 3px 8px;
}}
QToolButton:hover {{ background-color: {t["button_hover"]}; }}
QToolButton:pressed {{ background-color: {t["button_active"]}; }}
QToolButton:disabled {{ color: {t["fg_dim"]}; }}

QPushButton {{
    background-color: {t["button_bg"]};
    color: {t["button_fg"]};
    border: 1px solid {t["border"]};
    border-radius: 4px;
    padding: 4px 10px;
}}
QPushButton:hover {{ background-color: {t["button_hover"]}; }}
QPushButton:pressed {{ background-color: {t["button_active"]}; }}
QPushButton:disabled {{ color: {t["fg_dim"]}; }}

/* Accent (confirm) and chip (cancel) dialog buttons */
QPushButton#accentBtn {{
    background-color: {t["accent"]};
    color: #ffffff;
    border: none;
    font-weight: bold;
    padding: 6px 18px;
}}
QPushButton#accentBtn:hover {{ background-color: {accent_hover}; }}
QPushButton#chipBtn {{
    background-color: {t["bg_tertiary"]};
    color: {t["fg"]};
    border: none;
    padding: 6px 16px;
}}
QPushButton#chipBtn:hover {{ background-color: {t["border"]}; }}

/* ── Checkboxes ──────────────────────────────────────────────────── */
QCheckBox {{
    background: transparent;
    color: {t["check_fg"]};
    spacing: 5px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {t["border_light"]};
    border-radius: 3px;
    background-color: {t["check_bg"]};
}}
QCheckBox::indicator:checked {{
    background-color: {t["check_select"]};
    border-color: {t["check_select"]};
}}

/* ── Entries ─────────────────────────────────────────────────────── */
QLineEdit {{
    background-color: {t["entry_bg"]};
    color: {t["entry_fg"]};
    border: 1px solid {t["entry_border"]};
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: {t["text_select_bg"]};
    selection-color: {t["list_select_fg"]};
}}
QLineEdit:focus {{ border-color: {t["accent"]}; }}
QLineEdit[placeholderText] {{ color: {t["entry_fg"]}; }}

QPlainTextEdit, QTextEdit {{
    background-color: {t["text_bg"]};
    color: {t["text_fg"]};
    border: 1px solid {t["border"]};
    border-radius: 4px;
    selection-background-color: {t["text_select_bg"]};
    selection-color: {t["list_select_fg"]};
}}

/* ── Sidebar list ────────────────────────────────────────────────── */
QListWidget {{
    background-color: {t["list_bg"]};
    color: {t["list_fg"]};
    border: none;
    outline: none;
}}
QListWidget::item {{
    padding: 4px 6px;
    border-radius: 4px;
}}
QListWidget::item:hover {{ background-color: {t["bg_tertiary"]}; }}
QListWidget::item:selected {{
    background-color: {t["list_select_bg"]};
    color: {t["list_select_fg"]};
}}
QListWidget::item:disabled {{ color: {t["border"]}; }}

/* ── Splitter ────────────────────────────────────────────────────── */
QSplitter::handle {{
    background-color: {t["paned_sash"]};
}}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}

/* ── Menus ───────────────────────────────────────────────────────── */
QMenu {{
    background-color: {t["menu_bg"]};
    color: {t["menu_fg"]};
    border: 1px solid {t["border"]};
    padding: 4px 0;
}}
QMenu::item {{
    background: transparent;
    padding: 4px 22px;
}}
QMenu::item:selected {{
    background-color: {t["menu_active_bg"]};
    color: {t["menu_active_fg"]};
}}
QMenu::item:disabled {{ color: {t["fg_dim"]}; }}
QMenu::separator {{
    height: 1px;
    background-color: {t["separator"]};
    margin: 4px 8px;
}}

/* ── Scrollbars ──────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background-color: {t["scrollbar_trough"]};
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background-color: {t["scrollbar_bg"]};
    border-radius: 5px;
    min-height: 24px;
    margin: 1px;
}}
QScrollBar::handle:vertical:hover {{ background-color: {t["scrollbar_active"]}; }}
QScrollBar:horizontal {{
    background-color: {t["scrollbar_trough"]};
    height: 12px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background-color: {t["scrollbar_bg"]};
    border-radius: 5px;
    min-width: 24px;
    margin: 1px;
}}
QScrollBar::handle:horizontal:hover {{ background-color: {t["scrollbar_active"]}; }}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ── Status bar ──────────────────────────────────────────────────── */
QStatusBar {{
    background-color: {t["bg"]};
    color: {t["fg_dim"]};
    border-top: 1px solid {t["border"]};
    font-size: {small}pt;
}}
QStatusBar QLabel {{
    background: transparent;
    color: {t["fg_dim"]};
    font-size: {small}pt;
}}
QStatusBar::item {{ border: none; }}

QLabel {{ background: transparent; }}

/* ── Recycle box (LabelFrame look) ───────────────────────────────── */
QGroupBox {{
    background-color: {t["bg"]};
    border: 1px solid {t["border"]};
    border-radius: 4px;
    margin-top: 9px;
    padding: 5px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    color: {t["label_frame_fg"]};
}}

/* ── Styled frameless dialogs ────────────────────────────────────── */
QDialog#styledDialog {{ background-color: {t["border"]}; }}
QWidget#dialogCard {{ background-color: {t["bg_secondary"]}; }}
QWidget#dialogCard QLabel {{ background: transparent; }}
QLabel#dialogTitle {{ font-size: {fs + 1}pt; font-weight: bold; }}
QLabel#dialogDim {{ color: {t["fg_dim"]}; }}
QToolButton#dialogClose {{
    background: transparent;
    border: none;
    color: {t["fg_dim"]};
    padding: 0 2px;
}}
QToolButton#dialogClose:hover {{ color: {t["fg"]}; }}
"""
