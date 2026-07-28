"""M5 editing interactions: highlight/strike marker commands, task
checkboxes, find/replace bar, URL previews, notebook links, indent and
global search. Offscreen Qt via pytest-qt against temp data directories
(never the repo's live notebooks/)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QTextCursor

from noteboard.core.fonts import mono_font
from noteboard.core.storage import NoteStore
from noteboard.core.theme import THEMES
from noteboard.ui.editor.document import MarkerDocument
from noteboard.ui.editor.highlighter import MarkdownHighlighter
from noteboard.ui.editor.note_edit import NoteTextEdit
from noteboard.ui.global_search import GlobalSearchDialog
from noteboard.ui.main_window import MainWindow

DEFAULT = NoteStore.DEFAULT_NOTEBOOK  # "默认"


@pytest.fixture
def editor(qtbot):
    doc = MarkerDocument()
    hl = MarkdownHighlighter(doc.document, THEMES["dark"], 12, mono_font())
    ed = NoteTextEdit(doc, hl)
    ed.resize(600, 400)
    qtbot.addWidget(ed)
    ed.show()
    return ed


@pytest.fixture
def store(tmp_path):
    return NoteStore(str(tmp_path))


@pytest.fixture
def window(qtbot, store):
    win = MainWindow(store)
    win.url_previews.fetch_enabled = False  # never hit the network
    qtbot.addWidget(win)
    return win


def _select(ed, start, end):
    c = ed.textCursor()
    c.setPosition(start)
    c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    ed.setTextCursor(c)


def _click_pos(ed, doc_pos):
    """Viewport point over the character at *doc_pos*."""
    c = QTextCursor(ed.document())
    c.setPosition(doc_pos)
    r = ed.cursorRect(c)
    return QPoint(r.left() + 2, r.top() + r.height() // 2)


# ── highlight commands ───────────────────────────────────────────────────

def test_highlight_apply_produces_exact_markers(editor):
    editor.marker_doc.load("hello world\nsecond line")
    _select(editor, 2, 7)  # partial selection: v1 highlights whole lines
    editor.apply_highlight("yellow")
    assert editor.marker_doc.serialize() == \
        "[HL:yellow]hello world[/HL]\nsecond line"


def test_highlight_replace_and_remove(editor):
    editor.marker_doc.load("hello world")
    _select(editor, 0, 5)
    editor.apply_highlight("yellow")
    # a second color replaces the first (v1 strips all colors first)
    _select(editor, 0, 5)
    editor.apply_highlight("red")
    assert editor.marker_doc.serialize() == "[HL:red]hello world[/HL]"
    _select(editor, 0, editor.document().characterCount() - 1)
    editor.remove_highlight()
    assert editor.marker_doc.serialize() == "hello world"


def test_highlight_undo_roundtrip(editor):
    editor.marker_doc.load("hello world")
    _select(editor, 0, 5)
    editor.apply_highlight("green")
    assert editor.marker_doc.serialize() == "[HL:green]hello world[/HL]"
    editor.document().undo()  # one command == one undo step
    assert editor.marker_doc.serialize() == "hello world"
    editor.document().redo()
    assert editor.marker_doc.serialize() == "[HL:green]hello world[/HL]"


def test_toggle_line_highlight_cmd1_semantics(editor):
    editor.marker_doc.load("alpha\nbeta")
    cursor = editor.textCursor()
    cursor.setPosition(1)
    editor.setTextCursor(cursor)
    editor.toggle_line_highlight("green")  # Cmd+1
    assert editor.marker_doc.serialize() == "[HL:green]alpha[/HL]\nbeta"
    editor.toggle_line_highlight("green")  # same color again toggles off
    assert editor.marker_doc.serialize() == "alpha\nbeta"


def test_toggle_line_highlight_multiline_skips_empty(editor):
    editor.marker_doc.load("one\n\ntwo")
    _select(editor, 0, editor.document().characterCount() - 1)
    editor.toggle_line_highlight("red")
    assert editor.marker_doc.serialize() == \
        "[HL:red]one[/HL]\n\n[HL:red]two[/HL]"
    _select(editor, 0, editor.document().characterCount() - 1)
    editor.toggle_line_highlight("red")  # all non-empty lines have it: off
    assert editor.marker_doc.serialize() == "one\n\ntwo"


def test_toggle_line_highlight_via_keypress(editor, qtbot):
    editor.marker_doc.load("shortcut line")
    qtbot.keyClick(editor, Qt.Key.Key_2,
                   Qt.KeyboardModifier.ControlModifier)  # yellow
    assert editor.marker_doc.serialize() == "[HL:yellow]shortcut line[/HL]"


# ── strikethrough ────────────────────────────────────────────────────────

def test_strike_apply_and_undo(editor):
    editor.marker_doc.load("hello world")
    _select(editor, 6, 11)
    editor.apply_strikethrough()
    assert editor.marker_doc.serialize() == "hello [STRIKE]world[/STRIKE]"
    editor.document().undo()
    assert editor.marker_doc.serialize() == "hello world"


def test_strike_remove_toggles_back(editor):
    editor.marker_doc.load("hello world")
    _select(editor, 6, 11)
    editor.apply_strikethrough()
    # select the struck word between the markers and remove
    _select(editor, 14, 19)
    assert editor._strike_open_at(14)  # context menu would offer "remove"
    editor.remove_strikethrough()
    assert editor.marker_doc.serialize() == "hello world"


def test_strike_remove_splits_larger_span(editor):
    editor.marker_doc.load("[STRIKE]hello world[/STRIKE]")
    _select(editor, 14, 19)  # "world" inside the span
    editor.remove_strikethrough()
    assert editor.marker_doc.serialize() == \
        "[STRIKE]hello [/STRIKE]world"


# ── task checkboxes ──────────────────────────────────────────────────────

def test_checkbox_click_toggles_and_is_one_undo_step(editor, qtbot):
    editor.marker_doc.load("- [ ] todo item")
    pos = _click_pos(editor, 3)  # inside the [ ] box
    qtbot.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert editor.marker_doc.serialize() == "- [x] todo item"
    qtbot.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert editor.marker_doc.serialize() == "- [ ] todo item"
    editor.document().undo()  # one click == one undo step
    assert editor.marker_doc.serialize() == "- [x] todo item"
    editor.document().undo()
    assert editor.marker_doc.serialize() == "- [ ] todo item"


def test_click_outside_box_does_not_toggle(editor, qtbot):
    editor.marker_doc.load("- [ ] todo item")
    pos = _click_pos(editor, 9)  # over the task text, not the box
    qtbot.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert editor.marker_doc.serialize() == "- [ ] todo item"


# ── notebook links ───────────────────────────────────────────────────────

def test_notebook_link_ctrl_click_emits_signal(editor, qtbot):
    editor.marker_doc.load("go [[target notebook]] now")
    got = []
    editor.notebook_link_clicked.connect(got.append)
    qtbot.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ControlModifier,
                     _click_pos(editor, 8))
    assert got == ["target notebook"]


def test_notebook_link_plain_click_does_not_emit(editor, qtbot):
    editor.marker_doc.load("go [[target notebook]] now")
    got = []
    editor.notebook_link_clicked.connect(got.append)
    qtbot.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton,
                     pos=_click_pos(editor, 8))
    assert got == []


# ── indent / unindent ────────────────────────────────────────────────────

def test_tab_indents_multiline_selection_one_undo_step(editor, qtbot):
    editor.marker_doc.load("one\ntwo\nthree")
    _select(editor, 0, 10)  # spans all three lines
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.marker_doc.serialize() == "    one\n    two\n    three"
    editor.document().undo()
    assert editor.marker_doc.serialize() == "one\ntwo\nthree"


def test_shift_tab_unindents_up_to_four_spaces(editor, qtbot):
    editor.marker_doc.load("    one\n  two\nthree")
    _select(editor, 0, editor.document().characterCount() - 1)
    qtbot.keyClick(editor, Qt.Key.Key_Backtab,
                   Qt.KeyboardModifier.ShiftModifier)
    assert editor.marker_doc.serialize() == "one\ntwo\nthree"


def test_tab_without_selection_inserts_spaces(editor, qtbot):
    editor.marker_doc.load("ab")
    cursor = editor.textCursor()
    cursor.setPosition(1)
    editor.setTextCursor(cursor)
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.marker_doc.serialize() == "a    b"


# ── find / replace bar ───────────────────────────────────────────────────

def test_find_bar_counts_and_navigates(window):
    window.show()
    window.editor.insertPlainText("foo bar foo baz foo")
    fb = window.find_bar
    assert not fb.isVisible()
    window.toggle_find_bar()
    assert fb.isVisible()
    fb.search_entry.setText("foo")
    fb._do_search()
    nm = window.translator.tr("search_n_of_m")
    assert fb.count_label.text() == nm.format(1, 3)
    assert len(window.editor.extraSelections()) == 3
    fb.goto_next()
    assert fb.count_label.text() == nm.format(2, 3)
    fb.goto_next()
    fb.goto_next()  # wraps around
    assert fb.count_label.text() == nm.format(1, 3)
    fb.goto_prev()  # wraps backwards
    assert fb.count_label.text() == nm.format(3, 3)
    fb.close_bar()
    assert not fb.isVisible()
    assert window.editor.extraSelections() == []


def test_find_bar_prefills_from_selection(window):
    window.show()
    window.editor.insertPlainText("alpha beta gamma")
    _select(window.editor, 6, 10)  # "beta"
    window.find_bar.show_bar()
    assert window.find_bar.search_entry.text() == "beta"


def test_replace_current_and_all(window):
    window.show()
    window.editor.insertPlainText("foo bar foo baz foo")
    fb = window.find_bar
    fb.show_bar()
    fb.search_entry.setText("foo")
    fb._do_search()
    fb.replace_entry.setText("qux")
    fb.replace_current()
    assert window.marker_doc.serialize().count("qux") == 1
    fb.replace_all()
    assert window.marker_doc.serialize() == "qux bar qux baz qux"
    assert fb.count_label.text() == \
        window.translator.tr("replaced_n").format(2)
    window.marker_doc.document.undo()  # replace-all is one undo step
    assert window.marker_doc.serialize().count("qux") == 1


# ── URL previews ─────────────────────────────────────────────────────────

URL = "https://example.com/page"


def test_url_preview_inserted_ephemeral_and_removed(window):
    window.url_previews.cache[URL] = "Example Title"
    window.editor.insertPlainText(f"see {URL}\nnext line")
    before = window.marker_doc.serialize()
    window.url_previews.rescan()
    text = window.editor.toPlainText()
    assert "  Example Title" in text
    # serialization never contains the preview
    assert window.marker_doc.serialize() == before
    # a second rescan is a no-op (no duplicate previews)
    window.url_previews.rescan()
    assert window.editor.toPlainText() == text
    # deleting the URL removes the orphan preview
    start = window.editor.toPlainText().find(URL)
    c = QTextCursor(window.marker_doc.document)
    c.setPosition(start)
    c.setPosition(start + len(URL), QTextCursor.MoveMode.KeepAnchor)
    c.removeSelectedText()
    window.url_previews.rescan()
    assert "Example Title" not in window.editor.toPlainText()
    assert window.marker_doc.serialize() == "see \nnext line"


def test_url_preview_does_not_mark_dirty(window):
    window.url_previews.cache[URL] = "Example Title"
    window.editor.insertPlainText(URL)
    window.save_notes()
    assert not window._dirty
    window.url_previews.rescan()
    assert "  Example Title" in window.editor.toPlainText()
    assert not window._dirty


def test_cursor_jumps_over_ephemeral_preview_line(window, qtbot):
    window.show()
    window.url_previews.cache[URL] = "Example Title"
    window.editor.insertPlainText(f"{URL}\nlast line")
    window.url_previews.rescan()
    doc = window.marker_doc.document
    assert doc.blockCount() == 3  # url, preview, last line
    cursor = window.editor.textCursor()
    cursor.setPosition(0)
    window.editor.setTextCursor(cursor)
    qtbot.keyClick(window.editor, Qt.Key.Key_Down)
    # cursor skipped the ephemeral preview block onto "last line"
    assert window.editor.textCursor().blockNumber() == 2


def test_fetch_result_updates_cache_and_saves(window, store, qtbot):
    calls = []
    window.url_previews.save_cache = lambda cache: calls.append(dict(cache))
    window.url_previews._on_title_fetched(URL, "Fetched Title")
    assert window.url_previews.cache[URL] == "Fetched Title"
    assert calls == [{URL: "Fetched Title"}]


# ── text context menu ────────────────────────────────────────────────────

def _open_context_menu(editor, at=5):
    """Build the text context menu (without exec'ing it)."""
    return editor.build_text_context_menu(_click_pos(editor, at))


def test_context_menu_grays_out_without_selection(editor):
    editor.marker_doc.load("hello world")
    tr = editor.translator.tr
    menu = _open_context_menu(editor)
    acts = {a.text(): a for a in menu.actions() if a.text()}
    # stable structure: items present but disabled, never hidden
    assert not acts[tr("ctx_cut")].isEnabled()
    assert not acts[tr("ctx_copy")].isEnabled()
    assert not acts[tr("strikethrough")].isEnabled()
    assert not acts[tr("save_as_nb")].isEnabled()
    assert not acts[tr("copy_nb_link")].isEnabled()  # no provider wired
    hl_menu = next(a.menu() for a in menu.actions() if a.menu())
    hl_acts = {a.text(): a for a in hl_menu.actions()}
    assert len(hl_acts) == 6  # 5 colors + remove
    assert not hl_acts[tr("remove_highlight")].isEnabled()


def test_context_menu_enables_with_selection(editor):
    editor.marker_doc.load("[HL:red]hello world[/HL]")
    editor.notebook_name_provider = lambda: "mybook"
    _select(editor, 8, 13)
    tr = editor.translator.tr
    menu = _open_context_menu(editor)
    acts = {a.text(): a for a in menu.actions() if a.text()}
    assert acts[tr("ctx_cut")].isEnabled()
    assert acts[tr("ctx_copy")].isEnabled()
    assert acts[tr("strikethrough")].isEnabled()
    assert acts[tr("save_as_nb")].isEnabled()
    assert acts[tr("copy_nb_link")].isEnabled()
    hl_menu = next(a.menu() for a in menu.actions() if a.menu())
    hl_acts = {a.text(): a for a in hl_menu.actions()}
    assert hl_acts[tr("remove_highlight")].isEnabled()  # line has [HL:red]


def test_context_menu_strike_label_toggles(editor):
    editor.marker_doc.load("hello [STRIKE]world[/STRIKE]")
    _select(editor, 14, 19)  # inside the struck span
    tr = editor.translator.tr
    menu = _open_context_menu(editor)
    texts = [a.text() for a in menu.actions() if a.text()]
    assert tr("remove_strike") in texts
    assert tr("strikethrough") not in texts


def test_copy_notebook_link(editor):
    from PySide6.QtWidgets import QApplication
    editor.notebook_name_provider = lambda: "工作"
    editor.copy_notebook_link()
    assert QApplication.clipboard().text() == "[[工作]]"


# ── main window wiring ───────────────────────────────────────────────────

def test_notebook_link_switches_notebook(window, store):
    window._do_create_notebook("linked")
    window.switch_notebook(DEFAULT)
    window.open_notebook_link("linked")
    assert window.current_notebook == "linked"


def test_save_selection_flow_creates_notebook_with_content(window, store,
                                                          monkeypatch):
    window.editor.insertPlainText("keep this text")
    _select(window.editor, 0, 4)  # "keep"
    monkeypatch.setattr("noteboard.ui.dialogs.ask_input",
                        lambda *a, **k: "extracted")
    content = window.editor.selection_marker_text()
    assert content == "keep"
    window.save_selection_as_notebook(content)
    assert "extracted" in store.list_notebooks()
    assert store.load_note_text("extracted") == "keep"
    # selection replaced with heading + [[link]]
    assert "### extracted" in window.marker_doc.serialize()
    assert "[[extracted]]" in window.marker_doc.serialize()


# ── global search ────────────────────────────────────────────────────────

def test_global_search_hits_across_notebooks_and_jump(window, store, qtbot):
    window.editor.insertPlainText("alpha needle here")
    window.save_notes()
    window._do_create_notebook("second")
    window.editor.insertPlainText("first line\nanother needle line")
    window.save_notes()

    dlg = GlobalSearchDialog(window, window.translator.tr, store,
                             window.current_notebook,
                             window.marker_doc.serialize,
                             THEMES[window.theme_name])
    qtbot.addWidget(dlg)
    dlg.entry.setText("needle")
    dlg._do_search()
    assert {r[0] for r in dlg._results} == {DEFAULT, "second"}
    assert dlg.count_label.text() == \
        window.translator.tr("global_results_n").format(2)
    hit = next(r for r in dlg._results if r[0] == "second")
    assert hit[1] == 1  # 0-based line number
    assert "needle" in hit[2]

    got = []
    dlg.open_notebook_at.connect(
        lambda nb, ln, q: got.append((nb, ln, q)))
    row = next(i for i, r in enumerate(dlg._results) if r[0] == DEFAULT)
    dlg.listbox.setCurrentRow(row)
    dlg._jump_item(dlg.listbox.currentItem())
    assert got == [(DEFAULT, 0, "needle")]

    window._on_global_search_jump(*got[0])
    assert window.current_notebook == DEFAULT
    assert window.editor.textCursor().selectedText() == "needle"
    assert window.find_bar.search_entry.text() == "needle"


def test_global_search_empty_query_clears(window, store, qtbot):
    dlg = GlobalSearchDialog(window, window.translator.tr, store,
                             window.current_notebook,
                             window.marker_doc.serialize,
                             THEMES[window.theme_name])
    qtbot.addWidget(dlg)
    dlg.entry.setText("   ")
    dlg._do_search()
    assert dlg._results == []
    assert dlg.count_label.text() == ""
