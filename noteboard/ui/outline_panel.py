"""Floating outline / table-of-contents panel (M6).

Port of v1 _build_outline_panel / _update_outline / _on_outline_click /
_flash_heading_line / _highlight_outline_for_line / resize + font handlers
(QuickNoteBoard.py L6580-7035). The panel is a child widget overlaying the
editor, anchored to its TOP-RIGHT corner exactly like v1 _show_outline:
``place(relx=1.0, rely=0.0, anchor="ne", x=-25, y=5)`` — i.e. 25px in from
the right edge, 5px down from the top. Height is the persisted value, or
auto-fit ``n*30+40`` capped at 500 and clamped to the editor (v1).

Behaviors ported:
- headings (#/##/###) re-extracted on edits, debounced (v1 piggybacked on
  the markdown pass); auto-hides when the note has no headings;
- click scrolls the editor so the heading line is centered, and flashes
  the line for 1s (v1 _flash_heading_line, tag "outline_flash");
- the active heading (cursor / scroll position) carries a ▸ arrow and
  accent color, synced with a 220ms debounce; at the scroll edges the
  first/last heading is latched (v1 _do_outline_scroll_sync);
- highlighted heading lines ([HL:x]...) show a thin colored left bar
  (v1's "▎" glyph column in _update_outline);
- left-edge drag resizes width (150-500), bottom-edge drag resizes height
  (min 100, clamped to editor); sizes persist via the config flow;
- right-click menu: 字体放大 / 字体缩小 / 重置大小 (outline_font_size
  clamped 8-24; reset = 12 / 240 / auto height).

In v1 the document text carried no style markers (highlights were Tk
tags); in v2 they are literal, so heading matching tolerates a leading
[HL:color] wrapper and highlight colors carried in from a previous line
are read off the highlighter's block state.
"""

import re

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QTextCursor
from PySide6.QtWidgets import (QLabel, QListWidget, QListWidgetItem, QMenu,
                               QStyle, QStyledItemDelegate, QStyleOption,
                               QTextEdit, QToolButton, QWidget)

from noteboard.core.fonts import system_font
from noteboard.core.markers import MARKER_SPLIT_RE
from noteboard.core.theme import HIGHLIGHT_NAMES
from noteboard.ui.editor.highlighter import _HL_MASK, _HL_SHIFT

# v1 ^(#{1,3})\s+(.+) — v2 lines may be wrapped in literal [HL:color] markers.
HEADING_RE = re.compile(r'^(?:\[HL:(\w+)\])?(#{1,3})\s+(.+)')

UPDATE_MS = 300     # heading re-extract debounce (v1: the 300ms md pass)
ACTIVE_MS = 220     # active-heading sync debounce (v1 L6576 pattern)
FLASH_MS = 1000     # v1 _flash_heading_line auto-clear

MIN_WIDTH, MAX_WIDTH = 150, 500   # v1 _outline_resize_drag clamp
MIN_HEIGHT = 100                  # v1 _outline_vresize_drag clamp
RIGHT_OFFSET, TOP_OFFSET = 25, 5  # v1 _show_outline place() offsets
HANDLE = 5                        # v1 drag-handle thickness
FONT_MIN, FONT_MAX = 8, 24        # v1 _outline_font_increase/decrease

ROLE_BLOCK = Qt.ItemDataRole.UserRole
ROLE_LEVEL = Qt.ItemDataRole.UserRole + 1
ROLE_COLOR = Qt.ItemDataRole.UserRole + 2

_INDENT = {1: 0, 2: 12, 3: 24}  # v1 indent {1:"", 2:"  ", 3:"    "}


class _HeadingDelegate(QStyledItemDelegate):
    """Paints one outline row: [colored bar][▸ slot][indented title] —
    the fixed-column layout v1 built out of text columns."""

    def __init__(self, panel):
        super().__init__(panel)
        self._panel = panel

    def _font(self, level):
        # v1 _apply_outline_font_tags: h1 = sz+2 bold, h2 = sz, h3 = sz-2
        sz = self._panel.font_size
        sizes = {1: sz + 2, 2: sz, 3: max(6, sz - 2)}
        font = QFont(system_font(), sizes.get(level, sz))
        if level == 1:
            font.setBold(True)
        return font

    def paint(self, painter, option, index):
        panel = self._panel
        t = panel.theme
        rect = option.rect
        painter.save()
        if option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect, QColor(t["bg_tertiary"]))  # ol_hover
        level = index.data(ROLE_LEVEL) or 1
        color = index.data(ROLE_COLOR)
        active = index.row() == panel.active_index
        # Thin colored left bar for highlighted heading lines (v1 "▎").
        if color:
            painter.fillRect(
                QRect(rect.left() + 3, rect.top() + 2, 3, rect.height() - 4),
                QColor(t.get(f"hl_{color}", t["accent"])))
        font = self._font(level)
        painter.setFont(font)
        fm = QFontMetrics(font)
        if active:  # ▸ in the arrow slot (v1 ol_active)
            painter.setPen(QColor(t["accent"]))
            painter.drawText(
                QRect(rect.left() + 9, rect.top(), 14, rect.height()),
                Qt.AlignmentFlag.AlignVCenter, "▸")
        if active:
            pen = t["accent"]
        else:
            pen = t["fg_dim"] if level == 3 else t["fg"]
        painter.setPen(QColor(pen))
        text_x = rect.left() + 24 + _INDENT.get(level, 0)
        avail = rect.right() - text_x - 4
        text = fm.elidedText(index.data() or "",
                             Qt.TextElideMode.ElideRight, max(10, avail))
        painter.drawText(QRect(text_x, rect.top(), max(10, avail),
                               rect.height()),
                         Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()

    def sizeHint(self, option, index):
        fm = QFontMetrics(self._font(index.data(ROLE_LEVEL) or 1))
        return QSize(0, fm.height() + 8)  # v1 spacing1=4 + spacing3=4


class _Handle(QWidget):
    """Drag handle: bottom edge resizes height, left edge resizes width
    (v1 _outline_resize_* / _outline_vresize_*). Hover paints border."""

    def __init__(self, panel, horizontal):
        super().__init__(panel)
        self._panel = panel
        self._horizontal = horizontal  # True = bottom (height) handle
        self._hover = False
        self._drag = None
        self.setCursor(Qt.CursorShape.SizeVerCursor if horizontal
                       else Qt.CursorShape.SizeHorCursor)

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def paintEvent(self, event):
        if self._hover:
            QPainter(self).fillRect(self.rect(),
                                    QColor(self._panel.theme["border"]))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = (event.globalPosition().toPoint(),
                          self._panel.width(), self._panel.height())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        start, w0, h0 = self._drag
        g = event.globalPosition().toPoint()
        if self._horizontal:
            self._panel._resize_height_to(h0 + (g.y() - start.y()))
        else:
            # dragging the LEFT edge leftwards grows the panel (v1 dx)
            self._panel._resize_width_to(w0 + (start.x() - g.x()))
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            self._drag = None
            self._panel._resize_finished()
            event.accept()


class OutlinePanel(QWidget):

    def __init__(self, editor, translator, theme, cfg, save_config):
        super().__init__(editor)
        self.setObjectName("outlinePanel")
        self.editor = editor
        self.translator = translator
        self.theme = theme
        self.cfg = cfg
        self._save_config = save_config

        #: v1 _outline_visible — user toggle state, independent of the
        #: auto-hide that kicks in when the note has no headings.
        self.visible_flag = False
        self.headings = []      # [(block_number, level, title, hl_color)]
        self.active_index = -1
        self._active_source = "cursor"
        self._pre_flash = None  # extraSelections saved while flashing

        self.panel_width = int(cfg.get("outline_width") or 240)
        self.panel_height = int(cfg.get("outline_height") or 0)  # 0 = auto
        self.font_size = int(cfg.get("outline_font_size") or 12)

        # ── children (manual geometry, see resizeEvent) ──
        self.title_label = QLabel(self)
        self.title_label.setObjectName("outlineTitle")
        self.close_btn = QToolButton(self)
        self.close_btn.setObjectName("outlineClose")
        self.close_btn.setText("✕")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.toggle)
        self.list = QListWidget(self)
        self.list.setObjectName("outlineList")
        self.list.setSelectionMode(
            QListWidget.SelectionMode.NoSelection)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setMouseTracking(True)  # hover highlight (ol_hover)
        self.list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setFrameShape(self.list.Shape.NoFrame)
        self.list.setItemDelegate(_HeadingDelegate(self))
        self.list.itemClicked.connect(self._on_item_clicked)
        self.list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        self._left_handle = _Handle(self, horizontal=False)
        self._bottom_handle = _Handle(self, horizontal=True)

        # ── timers ──
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(UPDATE_MS)
        self._update_timer.timeout.connect(self.update_outline)
        self._active_timer = QTimer(self)
        self._active_timer.setSingleShot(True)
        self._active_timer.setInterval(ACTIVE_MS)
        self._active_timer.timeout.connect(self._sync_active)
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.setInterval(FLASH_MS)
        self._flash_timer.timeout.connect(self._clear_flash)

        editor.document().contentsChanged.connect(self._update_timer.start)
        editor.cursorPositionChanged.connect(self._schedule_cursor_sync)
        editor.verticalScrollBar().valueChanged.connect(
            self._schedule_scroll_sync)
        editor.installEventFilter(self)  # follow the editor's resizes

        self.apply_theme(theme)
        self.retranslate()
        self.hide()

    # ── theming / i18n ───────────────────────────────────────────────

    def apply_theme(self, theme):
        self.theme = theme
        t = theme
        self.setStyleSheet(
            f"#outlinePanel {{ background-color: {t['bg_secondary']};"
            f" border: 1px solid {t['border']}; }}"
            f" #outlineTitle {{ color: {t['fg_dim']};"
            f" background: transparent; font-weight: bold; }}"
            f" #outlineClose {{ color: {t['fg_dim']};"
            f" background: transparent; border: none; }}"
            f" #outlineClose:hover {{ color: {t['fg']}; }}"
            f" #outlineList {{ background-color: {t['bg_secondary']};"
            f" border: none; }}")
        self.list.viewport().update()

    def retranslate(self):
        self.title_label.setText(self.translator.tr("outline_title"))

    def paintEvent(self, event):
        # Plain QWidget subclasses need this for QSS background/border.
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget,
                                   opt, painter, self)

    # ── heading extraction (v1 _update_outline) ──────────────────────

    def update_outline(self):
        self._update_timer.stop()
        doc = self.editor.document()
        headings = []
        block = doc.begin()
        while block.isValid():
            m = HEADING_RE.match(block.text())
            if m:
                color = m.group(1)
                if not color:
                    color = self._carried_highlight(block)
                # drop residual style/object markers (e.g. trailing [/HL])
                title = MARKER_SPLIT_RE.sub("", m.group(3)).strip()
                headings.append((block.blockNumber(), len(m.group(2)),
                                 title, color))
            block = block.next()
        self.headings = headings

        self.list.clear()
        for _block_no, level, title, color in headings:
            item = QListWidgetItem(title)
            item.setData(ROLE_LEVEL, level)
            item.setData(ROLE_COLOR, color or "")
            self.list.addItem(item)
        # Outline rebuilt: reset the active tracker (v1) and re-derive it.
        self.active_index = -1

        # v1: auto-hide with no headings; show when toggled on.
        if not headings:
            self.hide()
        elif self.visible_flag:
            self.show_panel()
            self.set_active_for_line(self.editor.textCursor().blockNumber())

    @staticmethod
    def _carried_highlight(block):
        """Highlight color carried into *block* from a multi-line [HL:]
        span, read from the highlighter's packed block state."""
        prev = block.previous()
        state = prev.userState() if prev.isValid() else -1
        if state > 0:
            idx = (state >> _HL_SHIFT) & _HL_MASK
            if 0 < idx <= len(HIGHLIGHT_NAMES):
                return HIGHLIGHT_NAMES[idx - 1]
        return None

    # ── show / hide / geometry (v1 _toggle_outline / _show_outline) ──

    def toggle(self):
        self.visible_flag = not self.visible_flag
        self.cfg["outline_visible"] = self.visible_flag
        if self.visible_flag:
            self.update_outline()  # shows itself when there are headings
        else:
            self.hide()
        self._save_config()

    def show_panel(self):
        n = len(self.headings)
        if n == 0:
            return
        if self.panel_height > 0:
            height = self.panel_height
        else:
            height = min(n * 30 + 40, 500)  # v1 auto-fit
        eh = self.editor.height()
        if eh > 50:
            height = min(height, eh - 10)
        width = self.panel_width
        self.setGeometry(self.editor.width() - RIGHT_OFFSET - width,
                         TOP_OFFSET, width, height)
        self.show()
        self.raise_()

    def resizeEvent(self, event):
        w, h = self.width(), self.height()
        self._left_handle.setGeometry(0, 0, HANDLE, h - HANDLE)
        self._bottom_handle.setGeometry(0, h - HANDLE, w, HANDLE)
        th = max(self.title_label.sizeHint().height(),
                 self.close_btn.sizeHint().height())
        self.title_label.setGeometry(HANDLE + 4, 4, w - HANDLE - 34, th)
        self.close_btn.setGeometry(w - 26, 4, 22, th)
        self.list.setGeometry(HANDLE + 2, 4 + th + 2,
                              w - HANDLE - 4, h - HANDLE - th - 12)
        super().resizeEvent(event)

    def eventFilter(self, obj, event):
        if obj is self.editor and event.type() == QEvent.Type.Resize:
            if self.visible_flag and self.headings:
                self.show_panel()  # stay glued to the top-right corner
        return super().eventFilter(obj, event)

    # ── resize handles → persisted size ──────────────────────────────

    def _resize_width_to(self, new_width):
        self.panel_width = max(MIN_WIDTH, min(MAX_WIDTH, int(new_width)))
        self.cfg["outline_width"] = self.panel_width
        self.show_panel()

    def _resize_height_to(self, new_height):
        h = max(MIN_HEIGHT, int(new_height))
        eh = self.editor.height()
        if eh > 50:
            h = min(h, eh - 10)
        self.panel_height = h
        self.cfg["outline_height"] = h
        self.show_panel()

    def _resize_finished(self):
        self._persist()  # v1 _outline_resize_end → save_config

    def _persist(self):
        self.cfg["outline_width"] = self.panel_width
        self.cfg["outline_height"] = self.panel_height
        self.cfg["outline_font_size"] = self.font_size
        self._save_config()

    # ── click → jump + flash (v1 _on_outline_click) ──────────────────

    def _on_item_clicked(self, item):
        self.jump_to(self.list.row(item))

    def jump_to(self, row):
        if not (0 <= row < len(self.headings)):
            return
        block_no = self.headings[row][0]
        doc = self.editor.document()
        block = doc.findBlockByNumber(block_no)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        self.editor.setTextCursor(cursor)
        self._center_block(block)
        self._set_active(row)
        self._flash_block(block)

    def _center_block(self, block):
        """Scroll so the heading line sits at the vertical center (v1
        dlineinfo + yview_scroll dance)."""
        layout = self.editor.document().documentLayout()
        rect = layout.blockBoundingRect(block)
        vsb = self.editor.verticalScrollBar()
        target = int(rect.y() + rect.height() / 2
                     - self.editor.viewport().height() / 2)
        vsb.setValue(max(vsb.minimum(), min(vsb.maximum(), target)))

    def _flash_block(self, block):
        """v1 _flash_heading_line: highlight the line, auto-clear after 1s.
        Painted as an extraSelection appended to whatever is already there
        (find-bar matches survive the flash)."""
        if self._flash_timer.isActive():
            self._flash_timer.stop()
            self._clear_flash()
        sel = QTextEdit.ExtraSelection()
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                            QTextCursor.MoveMode.KeepAnchor)
        sel.cursor = cursor
        fmt = sel.format
        fmt.setBackground(QColor(self.theme["list_select_bg"]))
        sel.format = fmt
        self._pre_flash = list(self.editor.extraSelections())
        self.editor.setExtraSelections(self._pre_flash + [sel])
        self._flash_timer.start()

    def _clear_flash(self):
        if self._pre_flash is not None:
            self.editor.setExtraSelections(self._pre_flash)
            self._pre_flash = None

    # ── active heading sync (v1 _update_outline_active / scroll sync) ─

    def _schedule_cursor_sync(self):
        self._active_source = "cursor"
        self._active_timer.start()

    def _schedule_scroll_sync(self):
        self._active_source = "scroll"
        self._active_timer.start()

    def _sync_active(self):
        if not self.visible_flag or not self.headings:
            return
        if self._active_source == "scroll":
            vsb = self.editor.verticalScrollBar()
            if vsb.maximum() > 0 and vsb.value() >= vsb.maximum():
                line = self.headings[-1][0]   # v1 bottom-edge latch
            elif vsb.maximum() > 0 and vsb.value() <= vsb.minimum():
                line = self.headings[0][0]    # v1 top-edge latch
            else:
                # v1: probe ~1/4 down the viewport so the outline flips a
                # bit before the heading scrolls off the top.
                probe = QPoint(0, self.editor.viewport().height() // 4)
                line = self.editor.cursorForPosition(probe).blockNumber()
        else:
            line = self.editor.textCursor().blockNumber()
        self.set_active_for_line(line)

    def set_active_for_line(self, block_no):
        """v1 _highlight_outline_for_line: last heading at/before the line."""
        active = -1
        for i, (line, _level, _title, _color) in enumerate(self.headings):
            if line <= block_no:
                active = i
            else:
                break
        self._set_active(active)

    def _set_active(self, idx):
        if idx == self.active_index:
            return  # v1 skips repaint when unchanged
        self.active_index = idx
        if 0 <= idx < self.list.count():
            self.list.scrollToItem(self.list.item(idx))
        self.list.viewport().update()

    # ── context menu / font size (v1 _show_outline_context_menu) ─────

    def _show_context_menu(self, pos):
        tr = self.translator.tr
        menu = QMenu(self)
        menu.addAction(tr("font_larger"), self.font_increase)
        menu.addAction(tr("font_smaller"), self.font_decrease)
        menu.addSeparator()
        menu.addAction(tr("reset_size"), self.reset_size)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def _apply_font_size(self, size):
        self.font_size = size
        self.cfg["outline_font_size"] = size
        self.update_outline()  # rebuild rows so size hints refresh
        self._persist()

    def font_increase(self):
        self._apply_font_size(min(self.font_size + 1, FONT_MAX))

    def font_decrease(self):
        self._apply_font_size(max(self.font_size - 1, FONT_MIN))

    def reset_size(self):
        """v1 _outline_reset_size: font 12, width 240, height auto."""
        self.font_size = 12
        self.panel_width = 240
        self.panel_height = 0
        self.update_outline()
        if self.visible_flag and self.headings:
            self.show_panel()
        self._persist()
