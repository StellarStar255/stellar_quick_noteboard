"""Cross-notebook rich paste (v2.0.0 parity with v1's [INTERNAL:RICH:]
clipboard flow, QuickNoteBoard.py handle_copy ~L7370 /
_insert_serialized_at_cursor ~L7185): copying a selection that contains
image/file objects carries a private JSON payload; pasting it into a
notebook with a different attachments dir copies the attachment files
over (renaming on collision), carries filename_map entries, and stays
one undo step. Offscreen Qt via pytest-qt."""

import json
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QMimeData
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from noteboard.core.theme import THEMES
from noteboard.ui.editor.document import MarkerDocument
from noteboard.ui.editor.highlighter import MarkdownHighlighter
from noteboard.ui.editor.note_edit import (MARKER_MIME, RICH_MIME,
                                           NoteTextEdit)

IMG_NAME = "img_20250101_120000_deadbeef.png"
# collision re-suffix keeps the v1 scheme: {base}_{ts}_{uuid8}{ext}
RESUFFIXED_RE = re.compile(
    r"img_20250101_120000_deadbeef_\d{8}_\d{6}_[0-9a-f]{8}\.png")


def _make_board(qtbot, tmp_path, nb):
    attach = tmp_path / nb / "attachments"
    attach.mkdir(parents=True)
    md = MarkerDocument(attachments_dir=str(attach))
    saved = {}

    def saver(internal, original=None, path=None):
        if original:
            saved[internal] = {"name": original, "path": path}

    md.attachment_saver = saver
    md.filename_map = saved
    hl = MarkdownHighlighter(md.document, THEMES["dark"])
    editor = NoteTextEdit(md, hl)
    editor.notebook_name_provider = lambda: nb
    qtbot.addWidget(editor)
    return editor, md, attach


def _write_png(path, color="#aa3355"):
    img = QImage(20, 10, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    img.save(str(path), "PNG")


@pytest.fixture
def boards(qtbot, tmp_path):
    """Notebook A with a real png + filename_map entry, empty notebook B."""
    editor_a, md_a, attach_a = _make_board(qtbot, tmp_path, "A")
    editor_b, md_b, attach_b = _make_board(qtbot, tmp_path, "B")
    _write_png(attach_a / IMG_NAME)
    entry = {"name": "photo.png", "path": "/somewhere/photo.png"}
    (attach_a / "filename_map.json").write_text(
        json.dumps({IMG_NAME: entry}), encoding="utf-8")
    md_a.filename_map[IMG_NAME] = dict(entry)
    return (editor_a, md_a, attach_a), (editor_b, md_b, attach_b)


def _copy_all(editor, md, text):
    md.load(text)
    editor.selectAll()
    editor.copy()
    return QApplication.clipboard().mimeData()


# ── copy payload ─────────────────────────────────────────────────────────

def test_copy_with_objects_sets_json_payload_and_marker_text(boards):
    (editor_a, md_a, attach_a), _b = boards
    content = f"hello\n[IMAGE:{IMG_NAME}]\ntail"
    mime = _copy_all(editor_a, md_a, content)

    assert mime.hasFormat(RICH_MIME)
    payload = json.loads(bytes(mime.data(RICH_MIME)).decode("utf-8"))
    assert payload["source_notebook"] == "A"
    assert payload["source_attachments_dir"] == os.path.abspath(str(attach_a))
    assert payload["markers"] == content
    # plain-text fallback stays the raw marker text (v1 behavior)
    assert mime.text() == content
    # in-notebook fast path payload still present
    assert bytes(mime.data(MARKER_MIME)).decode("utf-8") == content


# ── cross-notebook paste ─────────────────────────────────────────────────

def test_cross_notebook_paste_copies_file_and_filename_map(boards):
    (editor_a, md_a, attach_a), (editor_b, md_b, attach_b) = boards
    content = f"hello\n[IMAGE:{IMG_NAME}]\ntail"
    _copy_all(editor_a, md_a, content)

    editor_b.paste()

    # attachment copied under its internal name (free in B)
    assert (attach_b / IMG_NAME).exists()
    assert ((attach_b / IMG_NAME).read_bytes()
            == (attach_a / IMG_NAME).read_bytes())
    # marker preserved; text around it survives
    assert md_b.serialize() == content
    # filename_map entry carried over (saver + doc map)
    assert md_b.filename_map[IMG_NAME] == {"name": "photo.png",
                                           "path": "/somewhere/photo.png"}
    # whole paste is ONE undo step
    editor_b.undo()
    assert md_b.serialize() == ""


def test_cross_notebook_collision_renames_with_v1_scheme(boards):
    (editor_a, md_a, attach_a), (editor_b, md_b, attach_b) = boards
    (attach_b / IMG_NAME).write_bytes(b"KEEP-B")  # name taken in target
    _copy_all(editor_a, md_a, f"x\n[IMAGE:{IMG_NAME}:240]\ny")

    editor_b.paste()

    out = md_b.serialize()
    m = re.search(r"\[IMAGE:([^:\]]+):240\]", out)
    assert m, f"unexpected serialization: {out!r}"
    new_name = m.group(1)
    assert new_name != IMG_NAME
    assert RESUFFIXED_RE.fullmatch(new_name)
    # copied under the new name; the target's own file is untouched
    assert ((attach_b / new_name).read_bytes()
            == (attach_a / IMG_NAME).read_bytes())
    assert (attach_b / IMG_NAME).read_bytes() == b"KEEP-B"
    # filename_map entry carried under the NEW internal name
    assert md_b.filename_map[new_name] == {"name": "photo.png",
                                           "path": "/somewhere/photo.png"}


def test_cross_notebook_paste_copies_file_object_and_thumb_twin(
        boards):
    (editor_a, md_a, attach_a), (editor_b, md_b, attach_b) = boards
    video = "clip_20250101_120000_cafe0001.mp4"
    (attach_a / video).write_bytes(b"not really a video")
    _write_png(attach_a / f"_thumb_{video}.png", "#112233")

    _copy_all(editor_a, md_a, f"see\n[FILE:{video}]")
    editor_b.paste()

    assert f"[FILE:{video}]" in md_b.serialize()
    assert (attach_b / video).read_bytes() == b"not really a video"
    # _thumb_ cache twin travels with the attachment
    assert (attach_b / f"_thumb_{video}.png").exists()


# ── same-notebook paste keeps the fast path ──────────────────────────────

def test_same_dir_paste_does_not_duplicate_files(boards):
    (editor_a, md_a, attach_a), _b = boards
    content = f"hello\n[IMAGE:{IMG_NAME}]"
    _copy_all(editor_a, md_a, content)
    before = sorted(os.listdir(attach_a))

    cursor = editor_a.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor_a.setTextCursor(cursor)
    editor_a.paste()

    assert sorted(os.listdir(attach_a)) == before  # no copy, no rename
    assert md_a.serialize().count(f"[IMAGE:{IMG_NAME}]") == 2


# ── missing source file ──────────────────────────────────────────────────

def test_missing_source_file_falls_through_to_marker_text(boards):
    (editor_a, md_a, attach_a), (editor_b, md_b, attach_b) = boards
    markers = f"a [IMAGE:ghost.png] b\n[IMAGE:{IMG_NAME}]"
    mime = QMimeData()
    mime.setData(RICH_MIME, json.dumps(
        {"source_notebook": "A",
         "source_attachments_dir": os.path.abspath(str(attach_a)),
         "markers": markers}).encode("utf-8"))
    editor_b.insertFromMimeData(mime)

    out = md_b.serialize()
    # missing file: marker inserted as-is, paste as a whole succeeds
    assert "[IMAGE:ghost.png]" in out
    assert not (attach_b / "ghost.png").exists()
    # the real attachment still made it over
    assert f"[IMAGE:{IMG_NAME}]" in out
    assert (attach_b / IMG_NAME).exists()
