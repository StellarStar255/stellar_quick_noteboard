"""MarkerDocument round-trip: load() -> serialize() must be byte-identical
for every fixture, survive typing+undo, and the highlighter's bit-packed
block states must propagate across multi-line [HL:]/[STRIKE] spans."""

import glob
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QTextCursor

from noteboard.core.theme import HIGHLIGHT_NAMES, THEMES
from noteboard.ui.editor.document import MarkerDocument
from noteboard.ui.editor.highlighter import MarkdownHighlighter

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
FIXTURES = sorted(glob.glob(os.path.join(FIXTURE_DIR, "*.txt")))
FIXTURE_IDS = [os.path.basename(p) for p in FIXTURES]


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _block_containing(document, needle):
    block = document.begin()
    while block.isValid():
        if needle in block.text():
            return block
        block = block.next()
    raise AssertionError(f"no block contains {needle!r}")


@pytest.mark.parametrize("path", FIXTURES, ids=FIXTURE_IDS)
def test_roundtrip_exact(qapp, path):
    text = _read(path)
    doc = MarkerDocument()
    doc.load(text)
    assert doc.serialize() == text


@pytest.mark.parametrize("path", FIXTURES, ids=FIXTURE_IDS)
def test_typing_then_undo_roundtrips(qapp, path):
    text = _read(path)
    doc = MarkerDocument()
    doc.load(text)
    cursor = QTextCursor(doc.document)
    cursor.setPosition(doc.document.characterCount() // 2)
    cursor.insertText("typed here")
    assert doc.serialize() != text
    doc.document.undo()
    assert doc.serialize() == text


@pytest.mark.parametrize("path", FIXTURES, ids=FIXTURE_IDS)
def test_roundtrip_with_highlighter_attached(qapp, path):
    # Highlighting must never alter content or undo state.
    text = _read(path)
    doc = MarkerDocument()
    doc.load(text)
    hl = MarkdownHighlighter(doc.document, THEMES["dark"])
    hl.rehighlight()
    assert doc.serialize() == text
    assert not doc.document.isUndoAvailable()


def test_multiline_hl_strike_block_states(qapp):
    text = _read(os.path.join(FIXTURE_DIR, "markers_rich.txt"))
    doc = MarkerDocument()
    doc.load(text)
    hl = MarkdownHighlighter(doc.document, THEMES["dark"])
    hl.rehighlight()

    strike_open = _block_containing(doc.document, "multi line strike")
    assert strike_open.userState() & 0x20  # strike continues to next line
    hl_open = _block_containing(doc.document, "multi line highlight")
    yellow = HIGHLIGHT_NAMES.index("yellow") + 1
    assert (hl_open.userState() >> 6) & 0x7 == yellow

    # Edit the middle of the multi-line HL span: the attached highlighter
    # reruns on the changed block; state must survive and nothing crashes.
    cursor = QTextCursor(hl_open)
    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    cursor.insertText(" edited")
    assert (hl_open.userState() >> 6) & 0x7 == yellow
    tail = _block_containing(doc.document, "second line")
    assert (tail.userState() >> 6) & 0x7 == 0  # [/HL] closes on that line
    assert " edited" in doc.serialize()
