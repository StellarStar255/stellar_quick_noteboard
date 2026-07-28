"""Close button hides to the system tray; only quit_app really exits."""

import pytest

from noteboard.core.storage import NoteStore
from noteboard.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = NoteStore(str(tmp_path))
    store.ensure_notebooks_dir()
    w = MainWindow(store)
    qtbot.addWidget(w)
    return w


def test_close_hides_when_tray_present(window):
    window.tray = object()  # offscreen has no real tray; presence is enough
    window.show()
    window.close()
    assert not window.isVisible()      # hidden to tray…
    assert not window._quitting if hasattr(window, "_quitting") else True


def test_quit_app_really_closes(window):
    window.tray = object()
    window.show()
    window.quit_app()
    assert window._quitting


def test_close_without_tray_quits_normally(window):
    window.tray = None
    window.show()
    assert window.close()  # accepted close event


def test_note_font_size_survives_restart(qtbot, tmp_path, monkeypatch):
    """A+/A- note size must survive a full restart AND a theme toggle —
    the window QSS font once reset the document's defaultFont."""
    monkeypatch.chdir(tmp_path)
    store = NoteStore(str(tmp_path))
    store.ensure_notebooks_dir()
    w = MainWindow(store)
    qtbot.addWidget(w)
    w.increase_font()
    w.increase_font()
    w.quit_app()

    w2 = MainWindow(NoteStore(str(tmp_path)))
    qtbot.addWidget(w2)
    assert w2.cfg["font_size"] == 16
    assert w2.marker_doc.document.defaultFont().pointSize() == 16
    w2.toggle_theme()
    assert w2.marker_doc.document.defaultFont().pointSize() == 16
