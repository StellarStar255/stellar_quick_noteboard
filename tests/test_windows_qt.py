"""M6 windows & panels: outline/TOC panel, floating notebook viewer
windows, and the backup restore dialog. Offscreen Qt via pytest-qt against
a temp data directory (never the repo's live notebooks/)."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QTextCursor

import noteboard.ui.backup_dialog as backup_dialog_mod
from noteboard.core.storage import NoteStore
from noteboard.core.theme import THEMES
from noteboard.ui import dialogs
from noteboard.ui.backup_dialog import BackupRestoreDialog
from noteboard.ui.main_window import MainWindow

DEFAULT = NoteStore.DEFAULT_NOTEBOOK  # "默认"

OUTLINE_DOC = "# One\ntext a\n## Two\ntext b\n### Three\nplain"


@pytest.fixture
def store(tmp_path):
    return NoteStore(str(tmp_path))


@pytest.fixture
def window(qtbot, store):
    win = MainWindow(store)
    qtbot.addWidget(win)
    return win


def _type(win, text):
    win.editor.insertPlainText(text)


def _append(editor, text):
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.insertPlainText(text)


def _seed_backup(tmp_path, nb, stamp, content):
    bdir = tmp_path / "backups"
    bdir.mkdir(exist_ok=True)
    path = bdir / f"{nb}_backup_{stamp}.txt"
    path.write_text(content, encoding="utf-8")
    return path.name


# ── outline panel ────────────────────────────────────────────────────────

def test_outline_extracts_headings(window):
    _type(window, OUTLINE_DOC)
    panel = window.outline
    panel.update_outline()
    assert [(lvl, title) for _b, lvl, title, _c in panel.headings] == \
        [(1, "One"), (2, "Two"), (3, "Three")]
    assert [b for b, *_rest in panel.headings] == [0, 2, 4]
    assert panel.list.count() == 3


def test_outline_toggle_via_toolbar_button(window):
    window.show()
    _type(window, "# Heading\nbody")
    window.btn_outline.click()
    assert window.outline.visible_flag
    assert window.cfg["outline_visible"] is True
    assert window.outline.isVisible()
    # anchored to the editor's top-right corner (v1 place ne, x=-25, y=5)
    geo = window.outline.geometry()
    assert geo.x() == window.editor.width() - 25 - window.outline.panel_width
    assert geo.y() == 5
    window.btn_outline.click()
    assert not window.outline.visible_flag
    assert not window.outline.isVisible()


def test_outline_auto_hides_without_headings(window):
    window.show()
    _type(window, "no headings anywhere")
    window.toggle_outline()
    assert window.outline.visible_flag  # user toggle stays on
    assert not window.outline.isVisible()  # but nothing to show (v1)


def test_outline_updates_on_edit_debounced(window, qtbot):
    _type(window, "# First\n")
    panel = window.outline
    panel.update_outline()
    assert len(panel.headings) == 1
    _append(window.editor, "\n## Second\n")
    assert panel._update_timer.isActive()
    qtbot.wait_until(lambda: len(panel.headings) == 2, timeout=3000)
    assert panel.headings[1][1:3] == (2, "Second")


def test_outline_click_jumps_and_flashes(window, qtbot):
    _type(window, OUTLINE_DOC)
    panel = window.outline
    panel.update_outline()
    assert window.editor.textCursor().blockNumber() == 5  # at the end
    panel._on_item_clicked(panel.list.item(0))
    assert window.editor.textCursor().blockNumber() == 0
    assert panel.active_index == 0
    # flash extra-selection on the heading line, auto-cleared after ~1s
    assert len(window.editor.extraSelections()) == 1
    qtbot.wait_until(lambda: window.editor.extraSelections() == [],
                     timeout=3000)


def test_outline_active_heading_follows_cursor(window, qtbot):
    _type(window, OUTLINE_DOC)
    panel = window.outline
    window.toggle_outline()
    assert panel.active_index == 2  # cursor at the end → last heading
    cursor = window.editor.textCursor()
    cursor.setPosition(0)
    window.editor.setTextCursor(cursor)  # schedules the 220ms sync
    qtbot.wait_until(lambda: panel.active_index == 0, timeout=3000)


def test_outline_highlighted_heading_carries_color(window):
    _type(window, "[HL:yellow]# Marked[/HL]\nplain\n# Clean\n")
    panel = window.outline
    panel.update_outline()
    assert panel.headings[0][2] == "Marked"  # markers stripped from title
    assert panel.headings[0][3] == "yellow"
    assert panel.headings[1][3] is None


def test_outline_size_and_font_persist_to_config(window, tmp_path):
    window.show()
    window.resize(800, 600)
    _type(window, "# H\n")
    window.toggle_outline()
    panel = window.outline
    panel._resize_width_to(320)
    panel._resize_height_to(260)
    panel._resize_finished()
    panel.font_increase()
    assert window.cfg["outline_width"] == 320
    assert window.cfg["outline_height"] == 260
    assert window.cfg["outline_font_size"] == 13
    window._save_config()
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["outline_width"] == 320
    assert cfg["outline_height"] == 260
    assert cfg["outline_font_size"] == 13
    assert cfg["outline_visible"] is True
    # v1 _outline_reset_size
    panel.reset_size()
    assert (panel.font_size, panel.panel_width, panel.panel_height) == \
        (12, 240, 0)


def test_outline_visible_restored_on_boot(qtbot, window, store):
    _type(window, "# Restored\n")
    window.save_notes()
    window.toggle_outline()
    window.close()
    win2 = MainWindow(store)
    qtbot.addWidget(win2)
    assert win2.outline.visible_flag
    assert len(win2.outline.headings) == 1


# ── floating notebook viewers ────────────────────────────────────────────

def test_viewer_opens_with_same_content(window, store):
    _type(window, "hello viewer")
    window.save_notes()
    viewer = window.open_notebook_viewer(DEFAULT)
    assert viewer.marker_doc.serialize() == "hello viewer"
    tr = window.translator.tr
    assert viewer.windowTitle() == f"{tr('nb_viewer_title')} - {DEFAULT}"
    assert not viewer.isModal()
    assert window.viewers == {DEFAULT: viewer}


def test_viewer_duplicate_open_refocuses(window):
    v1 = window.open_notebook_viewer(DEFAULT)
    v2 = window.open_notebook_viewer(DEFAULT)
    assert v1 is v2
    assert len(window.viewers) == 1


def test_viewer_save_reloads_main_editor(window, store):
    _type(window, "base")
    window.save_notes()
    viewer = window.open_notebook_viewer(DEFAULT)
    _append(viewer.editor, " plus")
    viewer.save_and_sync()  # Cmd+S path
    assert store.load_note_text(DEFAULT) == "base plus"
    assert window.marker_doc.serialize() == "base plus"


def test_viewer_autosave_debounced(window, store, qtbot):
    _type(window, "start")
    window.save_notes()
    viewer = window.open_notebook_viewer(DEFAULT)
    _append(viewer.editor, " autosaved")
    assert viewer._save_timer.isActive()
    qtbot.wait_until(
        lambda: store.load_note_text(DEFAULT) == "start autosaved",
        timeout=5000)


def test_viewer_close_saves_and_unregisters(window, store):
    _type(window, "keep")
    window.save_notes()
    viewer = window.open_notebook_viewer(DEFAULT)
    _append(viewer.editor, " me")
    viewer.close()
    assert store.load_note_text(DEFAULT) == "keep me"
    assert window.viewers == {}
    # close also synced the main editor (v1 on_viewer_close)
    assert window.marker_doc.serialize() == "keep me"


def test_main_save_pulls_from_open_viewer(window, store):
    """v1 direction (save_notes L3960 → _sync_from_viewer): a full main
    save lets the current notebook's open viewer WIN."""
    _type(window, "base")
    window.save_notes()
    viewer = window.open_notebook_viewer(DEFAULT)
    _append(viewer.editor, " viewer-edit")
    _append(window.editor, " main-edit")  # will be discarded, as v1
    window.save_notes()
    assert store.load_note_text(DEFAULT) == "base viewer-edit"
    assert window.marker_doc.serialize() == "base viewer-edit"


def test_switch_to_notebook_with_viewer_saves_it_first(window, store):
    window._do_create_notebook("other")  # creates + switches
    _type(window, "other base")
    window.save_notes()
    window.switch_notebook(DEFAULT)
    viewer = window.open_notebook_viewer("other")
    _append(viewer.editor, " from viewer")  # unsaved (timer pending)
    window.switch_notebook("other")  # v1 L2591: saves the viewer first
    assert window.marker_doc.serialize() == "other base from viewer"


def test_app_close_saves_open_viewer(window, store):
    window._do_create_notebook("other")
    window.switch_notebook(DEFAULT)
    viewer = window.open_notebook_viewer("other")
    viewer.editor.insertPlainText("viewer content")
    assert viewer._save_timer.isActive()  # pending, not yet on disk
    window.close()
    assert store.load_note_text("other") == "viewer content"
    assert window.viewers == {}


# ── backup restore dialog ────────────────────────────────────────────────

def _make_dialog(qtbot, window, store):
    backups = store.list_backups(DEFAULT)
    dlg = BackupRestoreDialog(window, window.translator.tr, DEFAULT,
                              backups, store.read_backup,
                              THEMES[window.theme_name])
    qtbot.addWidget(dlg)
    return dlg, backups


def test_backup_dialog_lists_newest_first_with_preview(qtbot, window,
                                                       store, tmp_path):
    _seed_backup(tmp_path, DEFAULT, "20240102_030405", "old content")
    _seed_backup(tmp_path, DEFAULT, "20250607_080910", "new content")
    dlg, backups = _make_dialog(qtbot, window, store)
    assert [b.filename for b in backups] == [
        f"{DEFAULT}_backup_20250607_080910.txt",
        f"{DEFAULT}_backup_20240102_030405.txt"]
    items = [dlg.listbox.item(i).text() for i in range(dlg.listbox.count())]
    assert "2025-06-07 08:09:10" in items[0]
    assert "2024-01-02 03:04:05" in items[1]
    assert "KB" in items[0]
    # newest is preselected and previewed (raw text, read-only, v1)
    assert dlg.preview.toPlainText() == "new content"
    assert dlg.preview.isReadOnly()
    dlg.listbox.setCurrentRow(1)
    assert dlg.preview.toPlainText() == "old content"


def test_backup_dialog_confirm_gates_restore(qtbot, window, store,
                                             tmp_path, monkeypatch):
    _seed_backup(tmp_path, DEFAULT, "20240102_030405", "snapshot")
    dlg, backups = _make_dialog(qtbot, window, store)
    monkeypatch.setattr(backup_dialog_mod, "ask_confirm",
                        lambda *a, **k: False)
    dlg._do_restore()
    assert dlg.selected is None
    assert dlg.result() == 0
    monkeypatch.setattr(backup_dialog_mod, "ask_confirm",
                        lambda *a, **k: True)
    dlg._do_restore()
    assert dlg.selected == backups[0].filename
    assert dlg.result() == 1  # accepted


def test_restore_replaces_note_and_snapshots_previous(window, store,
                                                      tmp_path):
    _type(window, "current stuff")
    window.save_notes()
    fname = _seed_backup(tmp_path, DEFAULT, "20240102_030405",
                         "restored stuff")
    window._restore_backup(fname)
    assert store.load_note_text(DEFAULT) == "restored stuff"
    assert window.marker_doc.serialize() == "restored stuff"
    assert not window._dirty
    # the replaced content was snapshotted to backups first (v1)
    newest = store.list_backups(DEFAULT)[0]
    assert newest.filename != fname
    assert store.read_backup(newest.filename) == "current stuff"


def test_restore_with_no_backups_alerts_only(window, monkeypatch):
    calls = []
    monkeypatch.setattr(dialogs, "show_alert",
                        lambda *a, **k: calls.append(a))
    window.show_restore_backup_dialog()
    assert len(calls) == 1
    tr = window.translator.tr
    assert calls[0][2] == tr("restore_title").format(DEFAULT)
    assert calls[0][3] == tr("no_backups")
