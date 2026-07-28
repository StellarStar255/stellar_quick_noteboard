"""Perf pass regressions: decoded images are installed as display-scaled
resources (memory / paint cost), the natural size stays available for
display_size math, and growing an image past the pre-scaled resource
re-decodes to a crisp larger one. Offscreen Qt via pytest-qt."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage

from noteboard.core.theme import THEMES
from noteboard.ui.editor.document import MarkerDocument, OBJECT_CHAR
from noteboard.ui.editor.highlighter import MarkdownHighlighter
from noteboard.ui.editor.note_edit import NoteTextEdit

BIG_W, BIG_H = 2400, 1400


@pytest.fixture
def workspace(qtbot, tmp_path):
    attach = tmp_path / "attachments"
    attach.mkdir()
    md = MarkerDocument(attachments_dir=str(attach))
    hl = MarkdownHighlighter(md.document, THEMES["dark"])
    editor = NoteTextEdit(md, hl)
    qtbot.addWidget(editor)
    editor.resize(900, 700)
    return editor, md, attach


def _make_png(path, w=BIG_W, h=BIG_H, color="#446688"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    img.save(str(path), "PNG")


def test_decoded_resource_is_display_scaled(qtbot, workspace):
    editor, md, attach = workspace
    _make_png(attach / "a.png")
    with qtbot.waitSignal(md.image_loaded, timeout=5000):
        md.load("x\n[IMAGE:a.png]\ny\n")
    key = "attach://a.png"
    res = md._loaded_images[key]
    # offscreen dpr is 1.0: resource is exactly the display width, not the
    # 2400px original (which would sit in memory and be rescaled per paint)
    assert res.width() == 400
    # natural size preserved for display_size / drag-resize math
    assert md._natural_sizes[key] == (BIG_W, BIG_H)
    assert md.display_size(key, 0) == (400, round(400 * BIG_H / BIG_W))
    assert md.serialize() == "x\n[IMAGE:a.png]\ny\n"


def test_batch_decode_fires_all_signals(qtbot, workspace):
    editor, md, attach = workspace
    for name in ("a.png", "b.png", "c.png"):
        _make_png(attach / name)
    seen = []
    md.image_loaded.connect(seen.append)
    md.load("[IMAGE:a.png]\n[IMAGE:b.png:600]\n[IMAGE:c.png]\n")
    qtbot.wait_until(lambda: len(seen) == 3, timeout=5000)
    assert sorted(seen) == ["a.png", "b.png", "c.png"]
    assert md._loaded_images["attach://a.png"].width() == 400
    assert md._loaded_images["attach://b.png"].width() == 600


def test_grow_past_scaled_resource_redecodes(qtbot, workspace):
    editor, md, attach = workspace
    _make_png(attach / "a.png")
    with qtbot.waitSignal(md.image_loaded, timeout=5000):
        md.load("x\n[IMAGE:a.png]\ny\n")
    key = "attach://a.png"
    assert md._loaded_images[key].width() == 400
    pos = md.document.toPlainText().index(OBJECT_CHAR)
    with qtbot.waitSignal(md.image_loaded, timeout=5000):
        assert md.set_image_width(pos, 800)
    qtbot.wait_until(lambda: md._loaded_images[key].width() == 800,
                     timeout=5000)
    assert md.serialize() == "x\n[IMAGE:a.png:800]\ny\n"
    # shrinking keeps the larger resource (no rescale churn on drags)
    md.set_image_width(pos, 200)
    assert md._loaded_images[key].width() == 800
    assert md.serialize() == "x\n[IMAGE:a.png:200]\ny\n"


def test_clear_caches_resets_target_widths(qtbot, workspace):
    editor, md, attach = workspace
    _make_png(attach / "a.png")
    with qtbot.waitSignal(md.image_loaded, timeout=5000):
        md.load("[IMAGE:a.png:700]\n")
    assert md._target_widths["attach://a.png"] == 700
    md.clear_caches()
    assert not md._loaded_images and not md._target_widths
    with qtbot.waitSignal(md.image_loaded, timeout=5000):
        md.load("[IMAGE:a.png]\n")
    assert md._loaded_images["attach://a.png"].width() == 400
