"""Tests for noteboard.core.markers — the exact v1 marker/markdown dialect."""

from pathlib import Path

from noteboard.core.markers import (
    URL_RE,
    classify_line,
    has_markers,
    inline_spans,
    strip_markers,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _classify_all(text):
    """Drive classify_line with fence-state tracking like v1 does."""
    infos = []
    in_fence = False
    for line in text.split("\n"):
        info = classify_line(line, in_fence=in_fence)
        if info.kind == "fence_open":
            in_fence = True
        elif info.kind == "fence_close":
            in_fence = False
        infos.append(info)
    return infos


# ── classify_line ────────────────────────────────────────────────────────────

def test_classify_markdown_basics_fixture():
    lines = _read("markdown_basics.txt").split("\n")
    infos = _classify_all("\n".join(lines))
    kinds = [i.kind for i in infos]

    assert kinds[0] == "heading1"
    assert kinds[1] == "heading2"
    assert kinds[2] == "heading3"
    assert kinds[3] == "plain"
    assert kinds[4] == "list"          # - dash
    assert kinds[5] == "list"          # * star
    assert kinds[6] == "plain"         # + is NOT a list marker in v1
    assert kinds[7] == "list"          # 1.
    assert kinds[8] == "list"          # 2.
    assert kinds[9] == "task"
    assert kinds[10] == "task_done"    # - [x]
    assert kinds[11] == "task_done"    # - [X]
    assert kinds[12] == "quote"
    assert kinds[13] == "quote"        # bare '>'
    assert kinds[14] == "fence_open"
    assert infos[14].lang == "python"
    assert kinds[15] == kinds[16] == kinds[17] == "code"
    assert kinds[18] == "fence_close"
    assert kinds[19] == "fence_open"
    assert infos[19].lang == "js"
    assert kinds[23] == "fence_close"
    assert kinds[24] == "hr"           # ---
    assert kinds[25] == "hr"           # ***
    assert kinds[26] == "hr"           # ___
    assert kinds[27] == "plain"        # inline-markdown line


def test_heading_marker_and_text_spans():
    info = classify_line("## Hello world")
    assert info.kind == "heading2"
    # v1 marker span includes the space after the hashes
    assert info.marker_span == (0, 3)
    assert info.text_span == (3, len("## Hello world"))


def test_task_fields():
    info = classify_line("  - [x] buy milk")
    assert info.kind == "task_done"
    assert info.checked is True
    assert info.indent == 2
    # box span runs through the closing ']'
    assert info.marker_span == (2, 7)
    open_info = classify_line("- [ ] todo")
    assert open_info.kind == "task"
    assert open_info.checked is False


def test_task_takes_precedence_over_list():
    assert classify_line("- [x] done").kind == "task_done"
    assert classify_line("- plain item").kind == "list"


def test_list_marker_spans_and_cjk_lookahead():
    info = classify_line("  * item")
    assert info.kind == "list"
    assert info.indent == 2
    assert info.marker_span == (2, 3)
    # v1 allows no space before non-ASCII text after the marker
    assert classify_line("-中文项目").kind == "list"
    # ...but requires a space before ASCII text
    assert classify_line("-noSpace").kind == "plain"


def test_hr_exactly_three_markers_like_v1():
    # v1's editor HR regex matches exactly three markers (opt. whitespace)
    assert classify_line("---").kind == "hr"
    assert classify_line("- - -").kind == "hr"
    assert classify_line("***").kind == "hr"
    assert classify_line("___").kind == "hr"
    # four or more do NOT match the v1 editor dialect
    assert classify_line("----").kind == "plain"


def test_quote_bare_marker():
    info = classify_line(">")
    assert info.kind == "quote"
    assert info.marker_span == (0, 1)


def test_fence_open_close_state():
    open_info = classify_line("```Python ", in_fence=False)
    assert open_info.kind == "fence_open"
    assert open_info.lang == "python"   # v1 lowercases and strips
    close_info = classify_line("```", in_fence=True)
    assert close_info.kind == "fence_close"
    # heading inside a fence is just code
    assert classify_line("# not a heading", in_fence=True).kind == "code"


def test_empty_fixture_classifies_plain():
    text = _read("empty.txt")
    assert text == ""
    assert classify_line(text).kind == "plain"


def test_no_trailing_newline_fixture():
    text = _read("no_trailing_newline.txt")
    assert not text.endswith("\n")
    infos = _classify_all(text)
    assert [i.kind for i in infos] == ["heading1", "plain"]


# ── inline_spans ─────────────────────────────────────────────────────────────

def test_inline_bold_italic_code_combo():
    line = "some **bold** and *italic* and `inline code` here"
    spans = inline_spans(line)
    kinds = {s.kind: s for s in spans}
    assert set(kinds) == {"bold", "italic", "code"}

    bold = kinds["bold"]
    assert line[bold.start:bold.end] == "**bold**"
    assert bold.text == "bold"
    assert bold.marker_spans == [(bold.start, bold.start + 2),
                                 (bold.end - 2, bold.end)]

    italic = kinds["italic"]
    assert line[italic.start:italic.end] == "*italic*"
    assert italic.text == "italic"

    code = kinds["code"]
    assert line[code.start:code.end] == "`inline code`"
    assert code.marker_spans == [(code.start, code.start + 1),
                                 (code.end - 1, code.end)]


def test_code_protects_interior_from_bold():
    spans = inline_spans("`code with **not bold** inside`")
    assert [s.kind for s in spans] == ["code"]


def test_bold_spanning_code_region_is_skipped():
    # v1 skips any bold/italic match overlapping an inline-code region
    spans = inline_spans("**bold spanning `code inside` is skipped in v1**")
    assert [s.kind for s in spans] == ["code"]


def test_double_star_not_italic():
    spans = inline_spans("**only bold**")
    assert [s.kind for s in spans] == ["bold"]


def test_notebook_link_span():
    line = "link to [[笔记本]] notebook"
    spans = inline_spans(line)
    nb = [s for s in spans if s.kind == "nb_link"]
    assert len(nb) == 1
    assert nb[0].text == "笔记本"
    assert line[nb[0].start:nb[0].end] == "[[笔记本]]"


def test_inline_spans_on_fixture_lines():
    for line in _read("markdown_basics.txt").split("\n"):
        inline_spans(line)  # must never raise on any fixture line


# ── has_markers / strip_markers ──────────────────────────────────────────────

def test_has_markers_true_false():
    assert has_markers(_read("markers_rich.txt")) is True
    assert has_markers(_read("markdown_basics.txt")) is False
    assert has_markers(_read("empty.txt")) is False
    assert has_markers("[IMAGE:a.png]") is True
    assert has_markers("[FILE:a.pdf]") is True
    assert has_markers("[STRIKE]x[/STRIKE]") is True
    assert has_markers("[HL:green]x[/HL]") is True
    assert has_markers("plain [BRACKET] text") is False


def test_strip_markers_plain_rendering():
    assert (strip_markers("before [STRIKE]struck text[/STRIKE] after")
            == "before struck text after")
    assert strip_markers("[HL:green]green highlight[/HL]") == "green highlight"
    assert strip_markers("[IMAGE:foo.png:300]") == ""
    assert strip_markers("[IMAGE:bar.png]") == ""
    assert strip_markers("[FILE:doc.pdf]") == ""
    # multi-line markers
    assert (strip_markers("[STRIKE]multi line strike\ncontinues[/STRIKE] done")
            == "multi line strike\ncontinues done")
    # text without markers passes through untouched (fast path)
    text = _read("markdown_basics.txt")
    assert strip_markers(text) == text


# ── URL_RE ───────────────────────────────────────────────────────────────────

def test_url_re_matches_v1_style_urls():
    m = URL_RE.search("visit https://example.com/page?a=1 and more")
    assert m and m.group(1) == "https://example.com/page?a=1"
    m = URL_RE.search("plain http://foo.bar/baz end")
    assert m and m.group(1) == "http://foo.bar/baz"
    # case-insensitive scheme
    assert URL_RE.search("HTTPS://EXAMPLE.COM/x").group(1) == "HTTPS://EXAMPLE.COM/x"


def test_url_re_stops_at_spaces_and_brackets():
    assert URL_RE.search("https://a.b/c d").group(1) == "https://a.b/c"
    assert URL_RE.search("[https://a.b/c]").group(1) == "https://a.b/c"
    assert URL_RE.search("<https://a.b/c>").group(1) == "https://a.b/c"
    assert URL_RE.search('"https://a.b/c"').group(1) == "https://a.b/c"
    assert URL_RE.search("https://a.b/c\nnext").group(1) == "https://a.b/c"


def test_url_re_no_match_without_scheme():
    assert URL_RE.search("www.example.com has no scheme") is None
