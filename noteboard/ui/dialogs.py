"""Styled dialogs: frameless themed input / alert / confirm / order.

Port of v1's _styled_input_dialog (QuickNoteBoard.py L2909) and _show_alert
(L2859) look: 1px hairline border, bg_secondary card, header that drags the
borderless window, accent confirm button, Esc/Return handling, centered
over the parent. Colors come from the QSS the main window applies (object
names styledDialog / dialogCard / accentBtn / chipBtn — see ui/qss.py).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)


class StyledDialog(QDialog):
    """Frameless themed dialog card with a draggable header."""

    def __init__(self, parent, title):
        super().__init__(parent)
        self.setObjectName("styledDialog")
        self.setWindowFlags(Qt.WindowType.Dialog
                            | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self._drag_offset = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)  # 1px hairline via dialog bg
        self._card = QWidget(self)
        self._card.setObjectName("dialogCard")
        outer.addWidget(self._card)

        self.body = QVBoxLayout(self._card)
        self.body.setContentsMargins(18, 14, 18, 16)
        self.body.setSpacing(0)

        # Header: title + ✕ close, doubles as the drag handle.
        self._header = QWidget(self._card)
        head = QHBoxLayout(self._header)
        head.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(title, self._header)
        self.title_label.setObjectName("dialogTitle")
        head.addWidget(self.title_label)
        head.addStretch(1)
        close_btn = QToolButton(self._header)
        close_btn.setObjectName("dialogClose")
        close_btn.setText("✕")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        head.addWidget(close_btn)
        self.body.addWidget(self._header)

    # Drag the borderless window by its header.
    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and event.position().y() <= self._header.geometry().bottom()
                + self.body.contentsMargins().top()):
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._center_over_parent()

    def _center_over_parent(self):
        parent = self.parentWidget()
        if parent is None:
            return
        pg = parent.window().frameGeometry()
        size = self.sizeHint()
        x = pg.x() + (pg.width() - size.width()) // 2
        # v1 centers input dialogs at 1/3 height; close enough for all.
        y = pg.y() + max(0, (pg.height() - size.height()) // 3)
        self.move(x, y)

    def _button_row(self, confirm_text, cancel_text=None):
        """Bottom-right button row; returns the accent confirm button."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 18, 0, 0)
        row.addStretch(1)
        if cancel_text is not None:
            cancel = QPushButton(cancel_text, self._card)
            cancel.setObjectName("chipBtn")
            cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel.clicked.connect(self.reject)
            row.addWidget(cancel)
            row.addSpacing(8)
        confirm = QPushButton(confirm_text, self._card)
        confirm.setObjectName("accentBtn")
        confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm.setDefault(True)
        row.addWidget(confirm)
        self.body.addLayout(row)
        return confirm


class AlertDialog(StyledDialog):
    """v1 _show_alert: title + message + accent OK, Esc/Return dismiss."""

    def __init__(self, parent, tr, title, message):
        super().__init__(parent, title)
        msg = QLabel(message, self._card)
        msg.setWordWrap(True)
        msg.setMaximumWidth(380)
        self.body.addSpacing(10)
        self.body.addWidget(msg)
        self._button_row(tr("confirm")).clicked.connect(self.accept)
        self.setMinimumWidth(320)


class ConfirmDialog(StyledDialog):
    """Two-button yes/no confirmation; exec() -> Accepted on confirm."""

    def __init__(self, parent, tr, title, message, confirm_text=None):
        super().__init__(parent, title)
        msg = QLabel(message, self._card)
        msg.setWordWrap(True)
        msg.setMaximumWidth(380)
        self.body.addSpacing(10)
        self.body.addWidget(msg)
        confirm = self._button_row(confirm_text or tr("confirm"),
                                   tr("cancel"))
        confirm.clicked.connect(self.accept)
        self.setMinimumWidth(320)


class InputDialog(StyledDialog):
    """v1 _styled_input_dialog: label + entry + cancel/confirm.

    *validator*(value) returns an error message to show (dialog stays
    open) or None to accept. Empty input never accepts (v1 do_create /
    do_rename simply ignore an empty submit)."""

    def __init__(self, parent, tr, title, label_text, initial="",
                 confirm_text=None, validator=None):
        super().__init__(parent, title)
        self._tr = tr
        self._validator = validator

        lbl = QLabel(label_text, self._card)
        lbl.setObjectName("dialogDim")
        self.body.addSpacing(16)
        self.body.addWidget(lbl)
        self.body.addSpacing(6)
        self.entry = QLineEdit(self._card)
        if initial:
            self.entry.setText(initial)
            self.entry.selectAll()
        self.body.addWidget(self.entry)

        confirm = self._button_row(confirm_text or tr("create"), tr("cancel"))
        confirm.clicked.connect(self.submit)
        self.entry.returnPressed.connect(self.submit)
        self.setMinimumWidth(360)
        self.entry.setFocus()

    def value(self):
        return self.entry.text().strip()

    def submit(self):
        value = self.value()
        if not value:
            return  # v1: empty submit does nothing, dialog stays open
        if self._validator is not None:
            error = self._validator(value)
            if error:
                show_alert(self, self._tr, self._tr("warning"), error)
                return
        self.accept()


class OrderDialog(StyledDialog):
    """v1 show_notebook_order_dialog: reorder notebooks with ↑↓/buttons."""

    def __init__(self, parent, tr, names):
        super().__init__(parent, tr("nb_order_title"))
        hint = QLabel(tr("order_hint"), self._card)
        hint.setObjectName("dialogDim")
        hint.setWordWrap(True)
        self.body.addSpacing(10)
        self.body.addWidget(hint)
        self.body.addSpacing(8)

        self.listbox = QListWidget(self._card)
        self.listbox.setMinimumSize(260, 240)
        for name in names:
            self.listbox.addItem(QListWidgetItem(name))
        if names:
            self.listbox.setCurrentRow(0)
        self.body.addWidget(self.listbox)

        row = QHBoxLayout()
        row.setContentsMargins(0, 12, 0, 0)
        up_btn = QPushButton(tr("up_btn"), self._card)
        up_btn.clicked.connect(self.move_up)
        down_btn = QPushButton(tr("down_btn"), self._card)
        down_btn.clicked.connect(self.move_down)
        row.addWidget(up_btn)
        row.addWidget(down_btn)
        row.addStretch(1)
        cancel = QPushButton(tr("cancel"), self._card)
        cancel.setObjectName("chipBtn")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton(tr("confirm"), self._card)
        confirm.setObjectName("accentBtn")
        confirm.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addSpacing(8)
        row.addWidget(confirm)
        self.body.addLayout(row)

    def _move(self, delta):
        row = self.listbox.currentRow()
        target = row + delta
        if row < 0 or not (0 <= target < self.listbox.count()):
            return
        item = self.listbox.takeItem(row)
        self.listbox.insertItem(target, item)
        self.listbox.setCurrentRow(target)

    def move_up(self):
        self._move(-1)

    def move_down(self):
        self._move(+1)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Up:
            self.move_up()
        elif event.key() == Qt.Key.Key_Down:
            self.move_down()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept()
        else:
            super().keyPressEvent(event)

    def order(self):
        return [self.listbox.item(i).text()
                for i in range(self.listbox.count())]


# ── Blocking convenience wrappers ──────────────────────────────────────

def show_alert(parent, tr, title, message):
    AlertDialog(parent, tr, title, message).exec()


def ask_confirm(parent, tr, title, message, confirm_text=None):
    dlg = ConfirmDialog(parent, tr, title, message, confirm_text)
    return dlg.exec() == QDialog.DialogCode.Accepted


def ask_input(parent, tr, title, label_text, initial="", confirm_text=None,
              validator=None):
    """Returns the accepted stripped value, or None on cancel."""
    dlg = InputDialog(parent, tr, title, label_text, initial=initial,
                      confirm_text=confirm_text, validator=validator)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.value()
    return None
