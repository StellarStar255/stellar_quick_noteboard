"""Dragging pinned notebooks must change their relative order (v1 bug fix).

Pinned notebooks sort by their position in the shortcuts list; the saved
"order" list cannot override that. An explicit rearrangement therefore has
to re-sequence the shortcuts too — these tests pin that behaviour.
"""

import os

import pytest

from noteboard.core.storage import NoteStore
from noteboard.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = NoteStore(str(tmp_path))
    store.ensure_notebooks_dir()
    for name in ("甲", "乙", "丙"):
        store.create_notebook(name)
    w = MainWindow(store)
    qtbot.addWidget(w)
    return w


def _pin_all(window, names):
    for name in names:
        window.pin_notebook(name, True)


def test_drag_reorders_pinned_notebooks(window):
    _pin_all(window, ["甲", "乙", "丙"])
    assert window.store.ordered_notebooks()[:3] == ["甲", "乙", "丙"]

    # Simulate the sidebar drag result: 丙 moved to the top.
    window._on_order_dragged(["丙", "甲", "乙", "默认"])

    assert window.store.ordered_notebooks()[:3] == ["丙", "甲", "乙"]
    _order, shortcuts = window.store.load_order()
    assert shortcuts == ["丙", "甲", "乙"]


def test_move_up_reorders_pinned_notebooks(window):
    _pin_all(window, ["甲", "乙"])
    window.move_notebook("乙", -1)
    assert window.store.ordered_notebooks()[:2] == ["乙", "甲"]


def test_drag_keeps_unpinned_out_of_shortcuts(window):
    _pin_all(window, ["甲", "乙"])
    window._on_order_dragged(["乙", "甲", "丙", "默认"])
    _order, shortcuts = window.store.load_order()
    assert shortcuts == ["乙", "甲"]
    assert "丙" not in shortcuts


def test_reorder_survives_restart(window, tmp_path):
    _pin_all(window, ["甲", "乙", "丙"])
    window._on_order_dragged(["乙", "丙", "甲", "默认"])
    fresh = NoteStore(str(tmp_path))
    assert fresh.ordered_notebooks()[:3] == ["乙", "丙", "甲"]
