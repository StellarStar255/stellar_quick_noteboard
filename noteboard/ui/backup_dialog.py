"""Backup restore dialog (M6).

Port of v1 show_restore_backup_dialog (QuickNoteBoard.py L3436-3570) on the
StyledDialog base: backups for the current notebook listed newest-first as
"timestamp · size KB" rows (raw stamp shown when it doesn't parse, exactly
NoteStore.list_backups' semantics), a dimmed read-only RAW-TEXT preview of
the selected backup (v1 shows the marker text verbatim, first 4000 chars),
and an accent 恢复此备份 button guarded by a restore_confirm_msg confirm.

The dialog only *selects*; the restore flow itself (snapshot current
content to backups first, then replace notes.txt and reload the editor)
lives in MainWindow._restore_backup. The empty state (no backups → alert
tr("no_backups"), no dialog at all) is handled by the caller too, matching
v1's early return.
"""

from PySide6.QtWidgets import QListWidget, QPlainTextEdit

from noteboard.ui.dialogs import StyledDialog, ask_confirm

PREVIEW_CHARS = 4000  # v1 f.read(4000)


class BackupRestoreDialog(StyledDialog):

    def __init__(self, parent, tr, notebook, backups, read_backup, theme):
        super().__init__(parent, tr("restore_title").format(notebook))
        self._tr = tr
        self._backups = backups          # [BackupInfo], newest first
        self._read_backup = read_backup  # callable(filename) -> str
        self.selected = None             # filename accepted for restore

        prefix = f"{notebook}_backup_"
        self.listbox = QListWidget(self._card)
        for info in backups:
            if info.timestamp is not None:
                shown = info.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            else:  # v1: unparsable stamp shown raw
                shown = info.filename[len(prefix):-4] \
                    if info.filename.startswith(prefix) else info.filename
            shown += f"   ·   {info.size / 1024:.1f} KB"
            self.listbox.addItem(f" {shown}")
        self.listbox.setFixedHeight(
            min(max(len(backups), 1), 10) * 24 + 8)
        self.body.addSpacing(10)
        self.body.addWidget(self.listbox)

        self.preview = QPlainTextEdit(self._card)
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(180)
        self.preview.setStyleSheet(  # v1: raw text in fg_dim over text_bg
            f"QPlainTextEdit {{ color: {theme['fg_dim']};"
            f" background-color: {theme['text_bg']};"
            f" border: 1px solid {theme['border']}; }}")
        self.body.addSpacing(8)
        self.body.addWidget(self.preview, 1)

        confirm = self._button_row(tr("restore_btn"), tr("cancel"))
        confirm.clicked.connect(self._do_restore)

        self.listbox.currentRowChanged.connect(self._show_preview)
        self.listbox.setCurrentRow(0)  # v1 selects + previews the newest
        self.resize(560, 480)          # v1 minimum dialog size

    def _show_preview(self, row):
        if not (0 <= row < len(self._backups)):
            return
        try:
            text = self._read_backup(
                self._backups[row].filename)[:PREVIEW_CHARS]
        except Exception as e:  # v1 shows the error in the preview pane
            text = str(e)
        self.preview.setPlainText(text)

    def _do_restore(self):
        """v1 do_restore: confirm, then hand the filename to the caller."""
        row = self.listbox.currentRow()
        if not (0 <= row < len(self._backups)):
            return
        if not ask_confirm(self, self._tr, self._tr("restore_btn"),
                           self._tr("restore_confirm_msg"),
                           confirm_text=self._tr("restore_btn")):
            return
        self.selected = self._backups[row].filename
        self.accept()
