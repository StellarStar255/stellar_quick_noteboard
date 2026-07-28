"""Image objects must never render unbounded (huge-image regression).

Root cause of the bug: an image object inserted while its attachment was
missing or its header unreadable got NO width/height on its char format;
once the shared resource key was later swapped for the real decoded
QImage (another insert of the same name queueing a decode, paste,
register_image), the unsized fragment rendered at natural pixel size —
thousands of px wide. Every insert path must therefore stamp a bounded
width/height, and _on_image_decoded must correct any fragment whose
geometry disagrees with display_size() once the natural size is known.
Offscreen Qt via pytest-qt."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QMimeData
from PySide6.QtGui import QColor, QImage, QTextFormat

from noteboard.core.theme import THEMES
from noteboard.ui.editor import attachments_ui
from noteboard.ui.editor.document import (MAX_IMAGE_WIDTH, MarkerDocument,
                                          OBJECT_CHAR, PLACEHOLDER_SIZE,
                                          PROP_IMAGE_WIDTH)
from noteboard.ui.editor.highlighter import MarkdownHighlighter
from noteboard.ui.editor.note_edit import MARKER_MIME, NoteTextEdit

BIG_W, BIG_H = 2400, 1400  # typical retina screenshot pixel size


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


def _image_fragments(md):
    """[(position, QTextImageFormat, rendered_width_px)] for real image
    objects, rendered width measured from the actual line layout."""
    doc = md.document
    doc.documentLayout().documentSize()  # force layout
    out = []
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                cf = frag.charFormat()
                if cf.isImageFormat():
                    fmt = cf.toImageFormat()
                    lay = block.layout()
                    rel = frag.position() - block.position()
                    rendered = None
                    line = lay.lineForTextPosition(rel)
                    if line.isValid():
                        x1 = line.cursorToX(rel)[0]
                        x2 = line.cursorToX(rel + 1)[0]
                        rendered = abs(x2 - x1)
                    out.append((frag.position(), fmt, rendered))
            it += 1
        block = block.next()
    return out


def _assert_all_bounded(md):
    frags = _image_fragments(md)
    assert frags
    for pos, fmt, rendered in frags:
        assert fmt.hasProperty(QTextFormat.ImageWidth), \
            f"unsized image fragment at {pos}"
        assert 0 < fmt.width() <= MAX_IMAGE_WIDTH
        assert 0 < fmt.height()
        if rendered is not None:
            assert rendered <= MAX_IMAGE_WIDTH + 10
    return frags


def test_load_sets_width_with_and_without_marker_width(qtbot, workspace):
    editor, md, attach = workspace
    _make_png(attach / "a.png")
    _make_png(attach / "b.png")
    with qtbot.waitSignal(md.image_loaded, timeout=5000):
        md.load("x\n[IMAGE:a.png:500]\n[IMAGE:b.png]\ny\n")
    frags = _assert_all_bounded(md)
    assert frags[0][1].width() == 500
    # width-less marker: min(natural, config image_width) = 400
    assert frags[1][1].width() == 400
    # aspect preserved from the 2400x1400 natural size
    assert frags[1][1].height() == round(400 * BIG_H / BIG_W)


def test_header_unreadable_but_decodable_bounded_after_swap(
        qtbot, workspace, monkeypatch):
    """read_image_size fails (partially-synced / exotic file) but the full
    decode succeeds: the fragment must start bounded (placeholder box) and
    settle at the proper display size — NOT the 2400px natural size."""
    editor, md, attach = workspace
    _make_png(attach / "weird.png")
    monkeypatch.setattr(attachments_ui, "read_image_size", lambda p: None)
    with qtbot.waitSignal(md.image_loaded, timeout=5000):
        md.load("x\n[IMAGE:weird.png]\ny\n")
    frags = _assert_all_bounded(md)
    pos, fmt, rendered = frags[0]
    assert fmt.width() == 400  # min(natural, config 400) after decode
    assert fmt.height() == round(400 * BIG_H / BIG_W)
    # marker text round-trips unchanged (no explicit width invented)
    assert int(fmt.property(PROP_IMAGE_WIDTH) or 0) == 0
    assert md.serialize() == "x\n[IMAGE:weird.png]\ny\n"
    # the decode-time geometry fix is a load-time decoration, not an edit
    assert not md.document.isModified()


def test_missing_file_fragment_stays_bounded_after_key_gets_real_image(
        qtbot, workspace):
    """The reported bug: fragment inserted while the file was missing,
    then the same attachment name becomes available and is inserted again
    (marker paste) — the async decode swaps the shared resource; the OLD
    fragment must not blow up to natural size."""
    editor, md, attach = workspace
    md.load("x\n[IMAGE:ghost.png]\ny\n")
    frags = _image_fragments(md)
    assert frags[0][1].width() == PLACEHOLDER_SIZE  # gray box, bounded
    # attachment appears (sync finished), user pastes the same marker
    _make_png(attach / "ghost.png")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    mime = QMimeData()
    mime.setData(MARKER_MIME, b"[IMAGE:ghost.png]")
    with qtbot.waitSignal(md.image_loaded, timeout=5000):
        editor.insertFromMimeData(mime)
    frags = _assert_all_bounded(md)
    assert len(frags) == 2
    for _pos, fmt, rendered in frags:
        assert fmt.width() == 400
        if rendered is not None:
            assert rendered == pytest.approx(400, abs=2)


def test_rich_marker_paste_sets_width(qtbot, workspace):
    editor, md, attach = workspace
    _make_png(attach / "a.png")
    md.load("start\n")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    mime = QMimeData()
    mime.setData(MARKER_MIME, b"[IMAGE:a.png:600] and [IMAGE:a.png]")
    with qtbot.waitSignal(md.image_loaded, timeout=5000):
        editor.insertFromMimeData(mime)
    frags = _assert_all_bounded(md)
    assert frags[0][1].width() == 600
    assert frags[1][1].width() == 400


def test_paste_bitmap_sets_width(qtbot, workspace):
    editor, md, attach = workspace
    md.load("start\n")
    big = QImage(2000, 1200, QImage.Format.Format_RGB32)
    big.fill(QColor("#aa3355"))
    big.setDevicePixelRatio(2.0)  # retina clipboard screenshot
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    mime = QMimeData()
    mime.setImageData(big)
    editor.insertFromMimeData(mime)
    frags = _assert_all_bounded(md)
    assert frags[0][1].width() == 400


def test_hl_span_over_object_char_keeps_size(qtbot, workspace):
    """[HL:]/[STRIKE]/URL layout formats merged over the U+FFFC object
    char must not strip the image format's width."""
    editor, md, attach = workspace
    _make_png(attach / "a.png")
    with qtbot.waitSignal(md.image_loaded, timeout=5000):
        md.load("[HL:yellow][IMAGE:a.png:500][/HL]\n"
                "[STRIKE][IMAGE:a.png][/STRIKE]\n"
                "# head [IMAGE:a.png:500] https://example.com\n")
    editor.highlighter.rehighlight()
    frags = _assert_all_bounded(md)
    for _pos, fmt, rendered in frags:
        if rendered is not None:
            assert rendered == pytest.approx(fmt.width(), abs=2)


def test_undo_of_delete_restores_sized_fragment(qtbot, workspace):
    editor, md, attach = workspace
    _make_png(attach / "a.png")
    with qtbot.waitSignal(md.image_loaded, timeout=5000):
        md.load("x\n[IMAGE:a.png:500]\ny\n")
    text_before = md.serialize()
    pos = md.document.toPlainText().index(OBJECT_CHAR)
    editor.delete_object_at(pos)
    assert "[IMAGE:" not in md.serialize()
    md.document.undo()
    frags = _assert_all_bounded(md)
    assert frags[0][1].width() == 500
    assert md.serialize() == text_before
