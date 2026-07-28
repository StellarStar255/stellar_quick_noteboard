"""Quick recycle box: a 3-line scratch editor whose button prepends the
content to history.txt (v1 recycle_frame / recycle_note, L822-839 & L1395).
"""

from PySide6.QtCore import Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QPlainTextEdit,
                               QPushButton)


class RecycleBox(QGroupBox):

    #: emitted with the stripped text when the user hits 回收
    recycle_requested = Signal(str)

    def __init__(self, translator, parent=None):
        super().__init__(parent)
        self.translator = translator

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        self.text = QPlainTextEdit(self)
        self.text.setTabChangesFocus(True)
        fm = QFontMetrics(self.text.font())
        self.text.setFixedHeight(fm.lineSpacing() * 3 + 14)  # 3 lines, as v1
        layout.addWidget(self.text, 1)

        self.button = QPushButton(self)
        self.button.clicked.connect(self._on_recycle)
        layout.addWidget(self.button)

        self.retranslate()

    def _on_recycle(self):
        content = self.text.toPlainText().strip()
        if not content:
            return
        self.recycle_requested.emit(content)
        self.text.clear()

    def retranslate(self):
        tr = self.translator.tr
        self.setTitle(tr("recycle_title"))
        self.button.setText(tr("recycle_btn"))
