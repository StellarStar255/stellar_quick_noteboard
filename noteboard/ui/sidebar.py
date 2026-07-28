"""Notebook sidebar: search box + notebook list + New/Manage buttons.

Port of the v1 sidebar (QuickNoteBoard.py __init__ L743-817): pinned
(shortcut) notebooks first with a ★ prefix, a dim divider row before the
rest, live search filter, drag-to-reorder, select-to-switch, double-click
and right-click both opening the notebook context menu.
"""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

_NAME_ROLE = Qt.ItemDataRole.UserRole  # actual notebook name (None = divider)


class Sidebar(QWidget):

    #: user selected a notebook in the list
    notebook_activated = Signal(str)
    #: context menu wanted for a notebook (name, global pos)
    context_requested = Signal(str, QPoint)
    #: context menu wanted on empty area (global pos)
    empty_context_requested = Signal(QPoint)
    #: drag-reorder finished; carries the full new name order
    order_dragged = Signal(list)
    new_requested = Signal()
    manage_requested = Signal()

    def __init__(self, translator, parent=None):
        super().__init__(parent)
        self.translator = translator
        self._notebooks = []
        self._shortcuts = []
        self._current = None
        self._refreshing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        self.search = QLineEdit(self)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._rebuild())
        layout.addWidget(self.search)

        self.listbox = QListWidget(self)
        self.listbox.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove)
        self.listbox.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.listbox.itemSelectionChanged.connect(self._on_selection)
        self.listbox.itemDoubleClicked.connect(self._on_double_click)
        self.listbox.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.listbox.customContextMenuRequested.connect(self._on_context)
        self.listbox.model().rowsMoved.connect(self._on_rows_moved)
        layout.addWidget(self.listbox, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(5)
        self.new_btn = QPushButton(self)
        self.new_btn.clicked.connect(self.new_requested)
        self.manage_btn = QPushButton(self)
        self.manage_btn.clicked.connect(self.manage_requested)
        btn_row.addWidget(self.new_btn, 1)
        btn_row.addWidget(self.manage_btn, 1)
        layout.addLayout(btn_row)

        self.retranslate()

    # ── population ───────────────────────────────────────────────────

    def refresh(self, notebooks, shortcuts, current):
        """Set the (already ordered) notebook list and re-render."""
        self._notebooks = list(notebooks)
        self._shortcuts = list(shortcuts)
        self._current = current
        self._rebuild()

    def _rebuild(self):
        """Port of v1 refresh_notebook_listbox: filter, ★ pins, divider."""
        self._refreshing = True
        try:
            self.listbox.clear()
            names = self._notebooks
            filter_text = self.search.text().strip().lower()
            if filter_text:
                names = [n for n in names if filter_text in n.lower()]
            shortcuts_set = set(self._shortcuts)
            any_pinned = any(n in shortcuts_set for n in names)
            sep_added = False
            for name in names:
                pinned = name in shortcuts_set
                if not pinned and any_pinned and not sep_added:
                    sep = QListWidgetItem("─" * 24)
                    sep.setFlags(Qt.ItemFlag.NoItemFlags)
                    sep.setData(_NAME_ROLE, None)
                    self.listbox.addItem(sep)
                    sep_added = True
                item = QListWidgetItem(f"★ {name}" if pinned else name)
                item.setData(_NAME_ROLE, name)
                self.listbox.addItem(item)
            self._highlight_current()
        finally:
            self._refreshing = False

    def _highlight_current(self):
        for i in range(self.listbox.count()):
            item = self.listbox.item(i)
            if item.data(_NAME_ROLE) == self._current:
                self.listbox.setCurrentItem(item)
                self.listbox.scrollToItem(item)
                return
        self.listbox.setCurrentItem(None)

    def set_current(self, name):
        self._current = name
        self._refreshing = True
        try:
            self._highlight_current()
        finally:
            self._refreshing = False

    # ── events ───────────────────────────────────────────────────────

    def _selected_name(self):
        items = self.listbox.selectedItems()
        if not items:
            return None
        return items[0].data(_NAME_ROLE)

    def _on_selection(self):
        if self._refreshing:
            return
        name = self._selected_name()
        if name is None:
            return
        if name != self._current:
            self.notebook_activated.emit(name)

    def _on_double_click(self, item):
        name = item.data(_NAME_ROLE)
        if name is not None:
            self.context_requested.emit(
                name, self.listbox.viewport().mapToGlobal(
                    self.listbox.visualItemRect(item).center()))

    def _on_context(self, pos):
        item = self.listbox.itemAt(pos)
        global_pos = self.listbox.viewport().mapToGlobal(pos)
        name = item.data(_NAME_ROLE) if item is not None else None
        if name is not None:
            self.listbox.setCurrentItem(item)
            self.context_requested.emit(name, global_pos)
        else:
            self.empty_context_requested.emit(global_pos)

    def _on_rows_moved(self, *_):
        """Drag-reorder finished: persist the full order (v1
        _on_listbox_drag_end rebuilds notebook_order from the list)."""
        if self._refreshing:
            return
        order = []
        for i in range(self.listbox.count()):
            name = self.listbox.item(i).data(_NAME_ROLE)
            if name is not None:
                order.append(name)
        self.order_dragged.emit(order)

    # ── i18n ─────────────────────────────────────────────────────────

    def retranslate(self):
        tr = self.translator.tr
        self.search.setPlaceholderText(tr("search_placeholder"))
        self.new_btn.setText(tr("new_btn"))
        self.manage_btn.setText(tr("manage_btn"))
