"""M3 attachments pipeline: paste (bitmap/files), async image loading,
drag-resize width property, delete, file chips and the v1 naming scheme.
Offscreen Qt via pytest-qt."""

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QColor, QImage, QTextDocument

from noteboard.core.theme import THEMES
from noteboard.ui.editor import attachments_ui
from noteboard.ui.editor.document import (MarkerDocument, OBJECT_CHAR,
                                          PROP_IMAGE_WIDTH)
from noteboard.ui.editor.highlighter import MarkdownHighlighter
from noteboard.ui.editor.note_edit import NoteTextEdit

# v1 naming scheme (paste_image / paste_files):
#   img_{%Y%m%d_%H%M%S}_{uuid4[:8]}.png   for pasted bitmaps
#   {base}_{%Y%m%d_%H%M%S}_{uuid4[:8]}{ext}  for imported files
PASTED_IMG_RE = re.compile(r"^img_\d{8}_\d{6}_[0-9a-f]{8}\.png$")
IMPORTED_RE = re.compile(r"^(.+)_\d{8}_\d{6}_[0-9a-f]{8}(\.[^.]+)?$")


@pytest.fixture
def workspace(qtbot, tmp_path):
    attach = tmp_path / "attachments"
    attach.mkdir()
    md = MarkerDocument(attachments_dir=str(attach))
    saved = {}

    def saver(internal, original=None, path=None):
        if original:
            saved[internal] = {"name": original, "path": path}

    md.attachment_saver = saver
    md.filename_map = saved
    hl = MarkdownHighlighter(md.document, THEMES["dark"])
    editor = NoteTextEdit(md, hl)
    qtbot.addWidget(editor)
    return editor, md, attach, saved


def _make_qimage(w=60, h=40, color="#336699"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    return img


def _object_positions(doc):
    text = doc.toPlainText()
    return [i for i, ch in enumerate(text) if ch == OBJECT_CHAR]


def _reload(md, text, attach):
    md2 = MarkerDocument(attachments_dir=str(attach))
    md2.filename_map = dict(md.filename_map)
    md2.load(text)
    return md2


# ── naming scheme ────────────────────────────────────────────────────────

def test_naming_scheme_matches_v1():
    assert PASTED_IMG_RE.match(attachments_ui.pasted_image_name())
    name = attachments_ui.internal_file_name("My Report.pdf")
    assert re.fullmatch(r"My Report_\d{8}_\d{6}_[0-9a-f]{8}\.pdf", name)
    # extensionless files keep no extension (v1 splitext behaviour)
    name = attachments_ui.internal_file_name("Makefile")
    assert re.fullmatch(r"Makefile_\d{8}_\d{6}_[0-9a-f]{8}", name)


# ── paste image bytes ────────────────────────────────────────────────────

def test_paste_image_roundtrips(workspace):
    editor, md, attach, _saved = workspace
    mime = QMimeData()
    mime.setImageData(_make_qimage())
    editor.insertFromMimeData(mime)

    out = md.serialize()
    m = re.fullmatch(r"\[IMAGE:(img_\d{8}_\d{6}_[0-9a-f]{8}\.png)\]\n", out)
    assert m, f"unexpected serialization: {out!r}"
    name = m.group(1)
    assert (attach / name).exists()

    # label line is ephemeral: present in the editor, absent when saved
    assert name in md.document.toPlainText()

    md2 = _reload(md, out, attach)
    assert md2.serialize() == out


def test_paste_image_default_width_caps_to_natural_and_config(workspace):
    editor, md, attach, _ = workspace
    # small image: natural 60px wins over config 400
    mime = QMimeData()
    mime.setImageData(_make_qimage(60, 40))
    editor.insertFromMimeData(mime)
    pos = _object_positions(md.document)[0]
    probe = md.document.findBlock(pos).begin().fragment()
    fmt = probe.charFormat().toImageFormat()
    assert fmt.width() == 60
    assert fmt.height() == 40

    # large image: config image_width 400 caps it
    md.document.clear()
    mime2 = QMimeData()
    mime2.setImageData(_make_qimage(1000, 500))
    editor.insertFromMimeData(mime2)
    pos = _object_positions(md.document)[0]
    fmt = (md.document.findBlock(pos).begin().fragment()
           .charFormat().toImageFormat())
    assert fmt.width() == 400
    assert fmt.height() == 200
    # no explicit width serialized — only display sizing changed
    assert ":400]" not in md.serialize()


# ── resize path ──────────────────────────────────────────────────────────

def test_resize_stores_width_and_roundtrips(workspace):
    editor, md, attach, _ = workspace
    mime = QMimeData()
    mime.setImageData(_make_qimage(600, 300))
    editor.insertFromMimeData(mime)
    before = md.serialize()

    pos = _object_positions(md.document)[0]
    assert md.set_image_width(pos, 300)
    # simulate drag continuation collapsing into the same undo step
    assert md.set_image_width(pos, 320, join=True)

    out = md.serialize()
    m = re.fullmatch(
        r"\[IMAGE:(img_\d{8}_\d{6}_[0-9a-f]{8}\.png):320\]\n", out)
    assert m, f"unexpected serialization: {out!r}"

    fmt = (md.document.findBlock(pos).begin().fragment()
           .charFormat().toImageFormat())
    assert fmt.property(PROP_IMAGE_WIDTH) == 320
    assert fmt.width() == 320
    assert fmt.height() == 160  # aspect kept

    md2 = _reload(md, out, attach)
    assert md2.serialize() == out

    # the whole "drag" is one undo step
    md.document.undo()
    assert md.serialize() == before


def test_resize_clamps_to_v1_range(workspace):
    editor, md, attach, _ = workspace
    mime = QMimeData()
    mime.setImageData(_make_qimage(600, 300))
    editor.insertFromMimeData(mime)
    pos = _object_positions(md.document)[0]
    md.set_image_width(pos, 10_000)
    assert ":800]" in md.serialize()
    md.set_image_width(pos, 1, join=True)
    assert ":50]" in md.serialize()


# ── delete object ────────────────────────────────────────────────────────

def test_delete_image_object_is_undoable(workspace):
    editor, md, attach, _ = workspace
    mime = QMimeData()
    mime.setImageData(_make_qimage())
    editor.insertFromMimeData(mime)
    before = md.serialize()
    assert before.startswith("[IMAGE:")

    pos = _object_positions(md.document)[0]
    editor.delete_object_at(pos)
    assert "[IMAGE:" not in md.serialize()

    md.document.undo()
    assert md.serialize() == before


# ── file chips ───────────────────────────────────────────────────────────

def test_paste_file_chip_serializes_and_maps(workspace, tmp_path):
    editor, md, attach, saved = workspace
    src = tmp_path / "notes ideas.txt"
    src.write_text("hello", encoding="utf-8")

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(src))])
    editor.insertFromMimeData(mime)

    out = md.serialize()
    m = re.fullmatch(
        r"\[FILE:(notes ideas_\d{8}_\d{6}_[0-9a-f]{8}\.txt)\]\n", out)
    assert m, f"unexpected serialization: {out!r}"
    internal = m.group(1)
    assert (attach / internal).exists()
    assert saved[internal]["name"] == "notes ideas.txt"
    assert saved[internal]["path"] == str(src)

    # chip resource exists and is a rendered image (not the blue M2 box)
    res = md.document.resource(QTextDocument.ResourceType.ImageResource,
                               QUrl(f"attachfile://{internal}"))
    assert isinstance(res, QImage) and not res.isNull()
    assert res.width() > res.height()  # pill shape, not a square swatch

    md2 = _reload(md, out, attach)
    assert md2.serialize() == out


def test_paste_image_file_inserts_image_marker(workspace, tmp_path):
    editor, md, attach, saved = workspace
    src = tmp_path / "photo.png"
    _make_qimage(80, 50).save(str(src), "PNG")

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(src))])
    editor.insertFromMimeData(mime)

    out = md.serialize()
    m = re.fullmatch(
        r"\[IMAGE:(photo_\d{8}_\d{6}_[0-9a-f]{8}\.png)\]\n", out)
    assert m, f"unexpected serialization: {out!r}"
    assert saved[m.group(1)]["name"] == "photo.png"
    md2 = _reload(md, out, attach)
    assert md2.serialize() == out


# ── async progressive loading ────────────────────────────────────────────

def test_async_load_swaps_placeholder_for_real_image(qtbot, tmp_path):
    attach = tmp_path / "attachments"
    attach.mkdir()
    name = "pic.png"
    _make_qimage(120, 90).save(str(attach / name), "PNG")

    md = MarkerDocument(attachments_dir=str(attach))
    text = f"before\n[IMAGE:{name}]\nafter"
    with qtbot.waitSignal(md.image_loaded, timeout=5000):
        md.load(text)

    res = md.document.resource(QTextDocument.ResourceType.ImageResource,
                               QUrl(f"attach://{name}"))
    assert isinstance(res, QImage)
    assert (res.width(), res.height()) == (120, 90)

    # sizing was fixed from the header before decode: no explicit marker
    # width -> min(natural, 400) = 120
    pos = _object_positions(md.document)[0]
    fmt = (md.document.findBlock(pos).begin().fragment()
           .charFormat().toImageFormat())
    assert fmt.width() == 120 and fmt.height() == 90

    # ephemeral label line renders but never serializes
    assert md.serialize() == text


def test_marker_width_wins_over_default(qtbot, tmp_path):
    attach = tmp_path / "attachments"
    attach.mkdir()
    name = "wide.png"
    _make_qimage(1000, 400).save(str(attach / name), "PNG")

    md = MarkerDocument(attachments_dir=str(attach))
    text = f"[IMAGE:{name}:250]"
    with qtbot.waitSignal(md.image_loaded, timeout=5000):
        md.load(text)
    pos = _object_positions(md.document)[0]
    fmt = (md.document.findBlock(pos).begin().fragment()
           .charFormat().toImageFormat())
    assert fmt.width() == 250 and fmt.height() == 100
    assert md.serialize() == text


def test_missing_attachment_keeps_placeholder_and_roundtrip(qtbot, tmp_path):
    md = MarkerDocument(attachments_dir=str(tmp_path))
    text = "x [IMAGE:gone.png] y [FILE:doc.pdf] z"
    md.load(text)
    assert md.serialize() == text
