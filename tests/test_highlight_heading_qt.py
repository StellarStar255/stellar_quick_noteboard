"""A [HL:color]-wrapped line keeps its markdown identity (bug fix).

Classification must look through [HL:]/[STRIKE] wrappers: a highlighted
heading keeps the heading font size, and a highlighted task line keeps a
clickable checkbox.
"""

import pytest

from noteboard.core.markers import strip_style_markers
from noteboard.core.theme import THEMES
from noteboard.ui.editor.document import MarkerDocument
from noteboard.ui.editor.highlighter import MarkdownHighlighter


from PySide6.QtGui import QTextCharFormat


def _formats_at(block, col):
    """All layout formats covering *col* in the block (copied — the
    FormatRange wrappers die with the temporary list)."""
    ranges = block.layout().formats()
    return [QTextCharFormat(fr.format) for fr in ranges
            if fr.start <= col < fr.start + fr.length]


@pytest.fixture
def highlighted_doc(qapp):
    doc = MarkerDocument()
    doc.load("[HL:green]### 标题文字[/HL]\n正文\n")
    hl = MarkdownHighlighter(doc.document, THEMES["dark"], base_font_size=12)
    hl.rehighlight()
    return doc


def test_strip_style_markers_maps_indices():
    stripped, imap = strip_style_markers("[HL:green]### 标题[/HL]")
    assert stripped == "### 标题"
    assert imap[0] == 10          # first '#' sits after the [HL:green] token
    assert imap[-1] == 15         # last char of 标题 before [/HL]


def test_highlighted_heading_keeps_heading_size(highlighted_doc):
    block = highlighted_doc.document.begin()
    text = block.text()
    col = text.index("标")  # inside the heading text
    fmts = _formats_at(block, col)
    sizes = [f.fontPointSize() for f in fmts if f.fontPointSize() > 1]
    assert 13 in [int(s) for s in sizes]  # heading3 = int(12 * 1.15)
    # and the green highlight background is applied to the same span
    bgs = [f.background().color().name() for f in fmts
           if f.background().style() != 0]
    assert THEMES["dark"]["hl_green"].lower() in bgs


def test_hl_wrapper_tokens_collapse(highlighted_doc):
    block = highlighted_doc.document.begin()
    fmts = _formats_at(block, 0)  # first char of the [HL:green] token
    assert any(f.fontPointSize() == 1 for f in fmts)


def test_plain_line_unaffected(highlighted_doc):
    block = highlighted_doc.document.begin().next()
    assert block.text() == "正文"
    for f in _formats_at(block, 0):
        assert f.fontPointSize() in (0, 12)  # 0 = unset (doc default)
