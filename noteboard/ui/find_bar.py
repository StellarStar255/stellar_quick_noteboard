"""In-note find & replace bar (port of v1 _build_search_bar L6032).

Hidden by default above the editor; Cmd/Ctrl+F toggles it. Live search is
debounced 150ms; matches are painted with QTextEdit.setExtraSelections
(all matches: theme list_select_bg; current match: accent), so the
document's char formats stay untouched. Enter/Shift+Enter navigate with
wraparound and an "n/m" counter; Esc closes and clears. The replace row
replaces the current match or all matches (single undo step).

Matching is plain-text over the document text — markers included, exactly
like v1 which searched the Tk widget's text.
"""

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QTextEdit, QToolButton, QVBoxLayout, QWidget)

SEARCH_DEBOUNCE_MS = 150  # v1 _schedule_search
SCROLL_MARGIN = 30


class FindBar(QWidget):

    def __init__(self, editor, translator, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.translator = translator
        self._matches = []   # [(start, end), ...] document offsets
        self._current = -1

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._timer.timeout.connect(self._do_search)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 2)
        outer.setSpacing(3)

        row1 = QHBoxLayout()
        row1.setSpacing(4)
        self.search_entry = QLineEdit(self)
        row1.addWidget(self.search_entry, 1)
        self.count_label = QLabel("", self)
        self.count_label.setMinimumWidth(56)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row1.addWidget(self.count_label)
        self.prev_btn = QToolButton(self)
        self.prev_btn.setText("▲")
        self.prev_btn.clicked.connect(self.goto_prev)
        row1.addWidget(self.prev_btn)
        self.next_btn = QToolButton(self)
        self.next_btn.setText("▼")
        self.next_btn.clicked.connect(self.goto_next)
        row1.addWidget(self.next_btn)
        self.close_btn = QToolButton(self)
        self.close_btn.setText("✕")
        self.close_btn.clicked.connect(self.close_bar)
        row1.addWidget(self.close_btn)
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(4)
        self.replace_entry = QLineEdit(self)
        row2.addWidget(self.replace_entry, 1)
        self.replace_btn = QPushButton(self)
        self.replace_btn.clicked.connect(self.replace_current)
        row2.addWidget(self.replace_btn)
        self.replace_all_btn = QPushButton(self)
        self.replace_all_btn.clicked.connect(self.replace_all)
        row2.addWidget(self.replace_all_btn)
        outer.addLayout(row2)

        self.search_entry.textChanged.connect(lambda *_: self._timer.start())
        self.search_entry.installEventFilter(self)
        self.replace_entry.installEventFilter(self)

        self.retranslate()
        self.hide()

    # ── show / hide ──────────────────────────────────────────────────────

    def toggle_bar(self):
        """v1 _toggle_search_bar."""
        if self.isVisible():
            self.close_bar()
        else:
            self.show_bar()

    def show_bar(self):
        """v1 _show_search_bar: show, prefill from the selection, focus."""
        self.show()
        cursor = self.editor.textCursor()
        sel = (cursor.selectedText().replace("\u2029", "\n")
               if cursor.hasSelection() else "")
        if sel and "\n" not in sel and len(sel) < 200:
            self.search_entry.setText(sel)
        self.search_entry.setFocus()
        self.search_entry.selectAll()
        if self.search_entry.text():
            self._do_search()

    def close_bar(self):
        """v1 _close_search_bar: hide, clear highlights, refocus editor."""
        self._timer.stop()
        self.hide()
        self._matches = []
        self._current = -1
        self.count_label.setText("")
        self.editor.setExtraSelections([])
        self.editor.setFocus()

    def refresh(self):
        """Re-run the search (after a notebook load etc.)."""
        if self.isVisible():
            self._do_search()

    # ── searching ────────────────────────────────────────────────────────

    def _do_search(self):
        self._timer.stop()
        self._matches = []
        self._current = -1
        query = self.search_entry.text()
        if not query:
            self.count_label.setText("")
            self.editor.setExtraSelections([])
            return
        text = self.editor.document().toPlainText().lower()
        q = query.lower()
        qlen = len(q)
        start = 0
        while True:
            i = text.find(q, start)
            if i == -1:
                break
            self._matches.append((i, i + qlen))
            start = i + max(1, qlen)
        if not self._matches:
            self.count_label.setText(
                self.translator.tr("search_n_of_m").format(0, 0))
            self.editor.setExtraSelections([])
            return
        # start at the match closest after the cursor (v1 _do_search)
        pos = self.editor.textCursor().position()
        self._current = next((i for i, (s, _e) in enumerate(self._matches)
                              if s >= pos), 0)
        self._update_highlights()

    def _update_highlights(self):
        """All matches in list_select_bg, current match in accent; scroll
        the current one into view and update the n/m counter."""
        t = self.editor.marker_doc.theme
        doc = self.editor.document()
        selections = []
        for i, (s, e) in enumerate(self._matches):
            sel = QTextEdit.ExtraSelection()
            c = QTextCursor(doc)
            c.setPosition(s)
            c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = c
            fmt = sel.format
            fmt.setBackground(QColor(
                t["accent"] if i == self._current else t["list_select_bg"]))
            fmt.setForeground(QColor(t["list_select_fg"]))
            sel.format = fmt
            selections.append(sel)
        self.editor.setExtraSelections(selections)
        self.count_label.setText(self.translator.tr("search_n_of_m").format(
            self._current + 1, len(self._matches)))
        self._scroll_to_current()

    def _scroll_to_current(self):
        if not self._matches:
            return
        s, _e = self._matches[self._current]
        c = QTextCursor(self.editor.document())
        c.setPosition(min(s, self.editor.document().characterCount() - 1))
        rect = self.editor.cursorRect(c)
        vsb = self.editor.verticalScrollBar()
        height = self.editor.viewport().height()
        if rect.top() < 0:
            vsb.setValue(vsb.value() + rect.top() - SCROLL_MARGIN)
        elif rect.bottom() > height:
            vsb.setValue(vsb.value() + rect.bottom() - height + SCROLL_MARGIN)

    def goto_next(self):
        if not self._matches:
            return
        self._current = (self._current + 1) % len(self._matches)
        self._update_highlights()

    def goto_prev(self):
        if not self._matches:
            return
        self._current = (self._current - 1) % len(self._matches)
        self._update_highlights()

    # ── replace ──────────────────────────────────────────────────────────

    def replace_current(self):
        """v1 _replace_current: verify the match is still fresh, replace,
        re-search (which advances to the next occurrence)."""
        if not self._matches or self._current < 0:
            return
        query = self.search_entry.text()
        if not query:
            return
        s, e = self._matches[self._current]
        doc = self.editor.document()
        c = QTextCursor(doc)
        c.setPosition(s)
        c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
        if c.selectedText().lower() != query.lower():
            self._do_search()  # buffer changed under us: just re-search
            return
        c.beginEditBlock()
        c.insertText(self.replace_entry.text())
        c.endEditBlock()
        self._do_search()

    def replace_all(self):
        """v1 _replace_all: one undo step for the whole batch."""
        query = self.search_entry.text()
        if not query:
            return
        self._do_search()
        if not self._matches:
            return
        replacement = self.replace_entry.text()
        doc = self.editor.document()
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        count = 0
        try:
            # reverse order keeps earlier offsets valid while editing
            for s, e in reversed(self._matches):
                c = QTextCursor(doc)
                c.setPosition(s)
                c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
                if c.selectedText().lower() == query.lower():
                    c.insertText(replacement)
                    count += 1
        finally:
            edit.endEditBlock()
        self._do_search()
        self.count_label.setText(
            self.translator.tr("replaced_n").format(count))

    # ── keys ─────────────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.close_bar()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if obj is self.search_entry:
                    if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                        self.goto_prev()
                    else:
                        self.goto_next()
                else:
                    self.replace_current()
                return True
        return super().eventFilter(obj, event)

    # ── i18n ─────────────────────────────────────────────────────────────

    def retranslate(self):
        tr = self.translator.tr
        self.search_entry.setPlaceholderText(tr("search_placeholder"))
        self.replace_entry.setPlaceholderText(tr("replace_placeholder"))
        self.replace_btn.setText(tr("replace_btn"))
        self.replace_all_btn.setText(tr("replace_all_btn"))
