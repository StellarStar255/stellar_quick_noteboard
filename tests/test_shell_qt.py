"""M4 application shell: boot, notebook lifecycle, config roundtrip,
autosave, word count, i18n and theming. Offscreen Qt via pytest-qt against
a temp data directory (never the repo's live notebooks/)."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from noteboard.core.storage import NoteStore
from noteboard.core.theme import THEMES
from noteboard.ui.dialogs import InputDialog, OrderDialog
from noteboard.ui.main_window import MainWindow

DEFAULT = NoteStore.DEFAULT_NOTEBOOK  # "默认"


@pytest.fixture
def store(tmp_path):
    return NoteStore(str(tmp_path))


@pytest.fixture
def window(qtbot, store):
    win = MainWindow(store)
    qtbot.addWidget(win)
    return win


def _type(win, text):
    """Simulate an edit through the editor (marks the document dirty)."""
    win.editor.insertPlainText(text)


# ── boot ─────────────────────────────────────────────────────────────────

def test_boot_empty_data_dir_creates_default(window, store, tmp_path):
    assert (tmp_path / "notebooks" / DEFAULT).is_dir()
    assert window.current_notebook == DEFAULT
    assert window.windowTitle() == f"Quick Note Board - {DEFAULT}"
    assert DEFAULT in window.status_nb_label.text()


def test_boot_restores_saved_current_notebook(qtbot, store):
    store.ensure_notebooks_dir()
    store.create_notebook("work")
    store.save_config({"current_notebook": "work"})
    win = MainWindow(store)
    qtbot.addWidget(win)
    assert win.current_notebook == "work"


def test_boot_missing_saved_notebook_falls_back(qtbot, store):
    store.ensure_notebooks_dir()
    store.save_config({"current_notebook": "ghost"})
    win = MainWindow(store)
    qtbot.addWidget(win)
    assert win.current_notebook == DEFAULT


# ── switching saves the previous notebook ────────────────────────────────

def test_switch_saves_previous_notebook(window, store):
    _type(window, "hello from default")
    assert window._dirty
    window._do_create_notebook("second")  # creates + switches
    assert window.current_notebook == "second"
    assert store.load_note_text(DEFAULT) == "hello from default"
    # switching back loads the saved content
    window.switch_notebook(DEFAULT)
    assert window.marker_doc.serialize() == "hello from default"


def test_switch_cancels_pending_autosave(window):
    _type(window, "abc")
    assert window._autosave_timer.isActive()
    window._do_create_notebook("other")
    assert not window._autosave_timer.isActive()


# ── create / rename / delete flows ───────────────────────────────────────

def test_create_duplicate_rejected(window, store):
    assert window._do_create_notebook(DEFAULT) == "nb_exists"
    assert window._do_create_notebook("notes2") is None
    assert "notes2" in store.list_notebooks()
    assert window.current_notebook == "notes2"


def test_rename_default_blocked(window):
    assert window.current_notebook == DEFAULT
    assert window._do_rename_current("newname") == "no_rename_def"
    assert window.current_notebook == DEFAULT


def test_rename_flow(window, store):
    window._do_create_notebook("draft")
    assert window._do_rename_current(DEFAULT) == "nb_exists"
    assert window._do_rename_current("final") is None
    assert window.current_notebook == "final"
    assert "draft" not in store.list_notebooks()
    assert "final" in store.list_notebooks()
    assert window.windowTitle().endswith("final")
    # editor attachments dir follows the rename
    assert window.marker_doc.attachments_dir == \
        store.attachments_path("final")


def test_delete_last_notebook_blocked(window, store):
    assert window._do_delete_notebook(DEFAULT) == "no_delete_last"
    assert DEFAULT in store.list_notebooks()


def test_delete_current_falls_back_to_first_remaining(window, store):
    _type(window, "default content")
    window.save_notes()
    window._do_create_notebook("temp")
    _type(window, "temp content")
    assert window._do_delete_notebook("temp") is None
    assert window.current_notebook == DEFAULT
    assert "temp" not in store.list_notebooks()
    # deleted notebook's unsaved content must not leak into the fallback
    assert window.marker_doc.serialize() == "default content"


def test_delete_other_notebook_keeps_current(window, store):
    window._do_create_notebook("keepme")
    assert window._do_delete_notebook(DEFAULT) is None
    assert window.current_notebook == "keepme"
    assert store.list_notebooks() == ["keepme"]


# ── config roundtrip ─────────────────────────────────────────────────────

def test_config_roundtrip_on_close(qtbot, store, tmp_path):
    win = MainWindow(store)
    qtbot.addWidget(win)
    win.setGeometry(11, 22, 640, 480)
    win.toggle_theme()       # dark -> light
    win.switch_language()    # zh -> en
    win.close()

    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["geometry"] == "640x480+11+22"
    assert cfg["theme"] == "light"
    assert cfg["language"] == "en"
    assert cfg["current_notebook"] == DEFAULT
    assert cfg["sidebar_width"] > 1
    # every v1 config key is written
    from noteboard.core.storage import CONFIG_KEYS
    assert set(CONFIG_KEYS) <= set(cfg)

    win2 = MainWindow(store)
    qtbot.addWidget(win2)
    assert win2.theme_name == "light"
    assert win2.translator.language == "en"
    assert win2.geometry().width() == 640
    assert win2.geometry().height() == 480


def test_geometry_parse_negative_offsets(qtbot, store):
    store.ensure_notebooks_dir()
    store.save_config({"geometry": "500x400+-5+30"})
    win = MainWindow(store)
    qtbot.addWidget(win)
    g = win.geometry()
    assert (g.width(), g.height()) == (500, 400)
    assert (g.x(), g.y()) == (-5, 30)


# ── autosave ─────────────────────────────────────────────────────────────

def test_autosave_fires(window, store, qtbot):
    _type(window, "autosaved text")
    assert store.load_note_text(DEFAULT) == ""
    qtbot.wait_until(
        lambda: store.load_note_text(DEFAULT) == "autosaved text",
        timeout=5000)
    assert not window._dirty


def test_manual_save_writes_backup(window, store, qtbot):
    _type(window, "v1")
    window.save_notes()
    assert store.load_note_text(DEFAULT) == "v1"
    _type(window, " v2")
    window.save_notes()  # snapshots the previous on-disk content
    qtbot.wait_until(lambda: len(store.list_backups(DEFAULT)) >= 1,
                     timeout=5000)
    window._pool.waitForDone(3000)
    assert store.read_backup(store.list_backups(DEFAULT)[0].filename) == "v1"


def test_empty_editor_never_clobbers_note(window, store):
    _type(window, "precious")
    window.save_notes()
    window.editor.selectAll()
    window.editor.textCursor().removeSelectedText()
    window.save_notes()
    assert store.load_note_text(DEFAULT) == "precious"


# ── word count ───────────────────────────────────────────────────────────

def test_word_count_updates(window, qtbot):
    _type(window, "hello world 你好")
    qtbot.wait_until(
        lambda: window.wordcount_label.text()
        == window.translator.tr("wc_stats").format(4, 14),
        timeout=3000)


# ── language toggle ──────────────────────────────────────────────────────

def test_language_toggle_relabels_ui(window):
    assert window.btn_save.text() == "保存"
    assert window.sidebar.new_btn.text() == "+ 新建"
    window.switch_language()
    assert window.btn_save.text() == "Save"
    assert window.sidebar.new_btn.text() == "+ New"
    assert window.recycle.button.text() == "Recycle"
    assert window.cfg["language"] == "en"
    window.switch_language()
    assert window.btn_save.text() == "保存"


# ── theme toggle ─────────────────────────────────────────────────────────

def test_theme_toggle_switches_qss(window):
    assert THEMES["dark"]["bg"] in window.styleSheet()
    window.toggle_theme()
    assert window.theme_name == "light"
    assert THEMES["light"]["bg"] in window.styleSheet()
    assert THEMES["dark"]["bg"] not in window.styleSheet()
    assert window.highlighter.colors is THEMES["light"]
    assert window.btn_theme.text() == THEMES["light"]["theme_icon"]


# ── sidebar ──────────────────────────────────────────────────────────────

def test_sidebar_lists_pins_first_with_divider(window, store):
    window._do_create_notebook("alpha")
    window._do_create_notebook("beta")
    window.pin_notebook("beta", True)
    lb = window.sidebar.listbox
    texts = [lb.item(i).text() for i in range(lb.count())]
    assert texts[0] == "★ beta"
    assert "─" in texts[1]  # divider row between pins and the rest
    _order, shortcuts = store.load_order()
    assert shortcuts == ["beta"]
    window.pin_notebook("beta", False)
    _order, shortcuts = store.load_order()
    assert shortcuts == []


def test_sidebar_search_filters(window):
    window._do_create_notebook("alpha")
    window._do_create_notebook("beta")
    window.sidebar.search.setText("alp")
    lb = window.sidebar.listbox
    texts = [lb.item(i).text() for i in range(lb.count())]
    assert texts == ["alpha"]
    window.sidebar.search.setText("")
    assert lb.count() == 3


def test_sidebar_selection_switches(window, qtbot):
    window._do_create_notebook("target")
    window.switch_notebook(DEFAULT)
    lb = window.sidebar.listbox
    for i in range(lb.count()):
        if lb.item(i).data(0x0100) == "target":  # Qt.UserRole
            lb.setCurrentItem(lb.item(i))
            break
    assert window.current_notebook == "target"


# ── recycle box ──────────────────────────────────────────────────────────

def test_recycle_box_prepends_history(window, store):
    window.recycle.text.setPlainText("first snippet")
    window.recycle.button.click()
    window.recycle.text.setPlainText("second snippet")
    window.recycle.button.click()
    history = store.read_history()
    assert history.index("second snippet") < history.index("first snippet")
    assert history.startswith("--- ")
    assert window.recycle.text.toPlainText() == ""


# ── toolbar toggles ──────────────────────────────────────────────────────

def test_sidebar_toggle_persists_visibility(window):
    assert window.sidebar_visible
    window.toggle_sidebar()
    assert not window.sidebar_visible
    assert not window.sidebar.isVisible()
    assert window.btn_sidebar.text() == "▶"
    assert window._collect_config()["sidebar_visible"] is False
    window.toggle_sidebar()
    assert window.sidebar_visible


def test_padding_and_icon_size_config(window):
    window.set_padding(20)
    assert window.cfg["text_padding"] == 20
    assert "padding-left: 20px" in window.editor.styleSheet()
    window.set_icon_size(32)
    assert window.cfg["icon_size"] == 32


def test_note_font_size_buttons(window):
    base = window.cfg["font_size"]
    window.increase_font()
    assert window.cfg["font_size"] == base + 2
    assert window.highlighter.base_font_size == base + 2
    window.decrease_font()
    assert window.cfg["font_size"] == base


def test_ui_font_size_updates_qss_and_label(window):
    window.set_ui_font_size(16)
    assert window.btn_ui_size.text() == "16px"
    assert "font-size: 16pt" in window.styleSheet()
    assert window.cfg["ui_font_size"] == 16


# ── dialogs ──────────────────────────────────────────────────────────────

def test_input_dialog_validator_blocks(qtbot, window):
    tr = window.translator.tr
    calls = []

    def validator(value):
        calls.append(value)
        return "boom" if value == "bad" else None

    dlg = InputDialog(window, tr, "t", "l", validator=validator)
    qtbot.addWidget(dlg)
    dlg.entry.setText("  good  ")
    dlg.submit()
    assert calls == ["good"]
    assert dlg.value() == "good"
    assert dlg.result() == 1  # accepted


def test_input_dialog_empty_never_accepts(qtbot, window):
    dlg = InputDialog(window, window.translator.tr, "t", "l")
    qtbot.addWidget(dlg)
    dlg.entry.setText("   ")
    dlg.submit()
    assert dlg.result() == 0


def test_order_dialog_moves(qtbot, window):
    dlg = OrderDialog(window, window.translator.tr, ["a", "b", "c"])
    qtbot.addWidget(dlg)
    dlg.listbox.setCurrentRow(2)
    dlg.move_up()
    assert dlg.order() == ["a", "c", "b"]
    dlg.move_up()
    assert dlg.order() == ["c", "a", "b"]
    dlg.move_up()  # already at top: no-op
    assert dlg.order() == ["c", "a", "b"]
    dlg.listbox.setCurrentRow(0)
    dlg.move_down()
    assert dlg.order() == ["a", "c", "b"]


# ── close ────────────────────────────────────────────────────────────────

def test_close_saves_notes_and_config(qtbot, store, tmp_path):
    win = MainWindow(store)
    qtbot.addWidget(win)
    win.editor.insertPlainText("closing content")
    win.close()
    assert store.load_note_text(DEFAULT) == "closing content"
    assert (tmp_path / "config.json").exists()
