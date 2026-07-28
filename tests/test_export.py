"""Tests for noteboard.core.export — zip roundtrip, markdown and HTML export."""

import os
import zipfile
from pathlib import Path

from noteboard.core.export import (
    content_to_html,
    export_markdown,
    export_zip,
    import_zip,
)

FIXTURES = Path(__file__).parent / "fixtures"

PNG_BYTES = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

DISPLAY_NAMES = {"foo.png": "Foo Original.png", "doc.pdf": "报告.pdf"}


def display_name_fn(internal_name):
    return DISPLAY_NAMES.get(internal_name, internal_name)


def _make_notebook(root, name="MyNotes"):
    nb = root / name
    (nb / "attachments").mkdir(parents=True)
    (nb / "notes.txt").write_text(
        FIXTURES.joinpath("markers_rich.txt").read_text(encoding="utf-8"),
        encoding="utf-8")
    (nb / "attachments" / "foo.png").write_bytes(PNG_BYTES)
    (nb / "attachments" / "doc.pdf").write_bytes(b"%PDF-1.4 fake")
    return nb


# ── export_zip / import_zip ──────────────────────────────────────────────────

def test_zip_roundtrip(tmp_path):
    nb = _make_notebook(tmp_path)
    out_zip = tmp_path / "MyNotes.zip"
    export_zip(str(nb), str(out_zip))

    assert out_zip.exists()
    with zipfile.ZipFile(out_zip) as zf:
        names = set(zf.namelist())
    assert "notes.txt" in names
    assert os.path.join("attachments", "foo.png") in names

    notebooks_dir = tmp_path / "notebooks"
    notebooks_dir.mkdir()
    final = import_zip(str(out_zip), str(notebooks_dir))
    assert final == "MyNotes"
    imported = notebooks_dir / final
    assert (imported / "notes.txt").read_text(encoding="utf-8") == \
        (nb / "notes.txt").read_text(encoding="utf-8")
    assert (imported / "attachments" / "foo.png").read_bytes() == PNG_BYTES
    assert (imported / "attachments").is_dir()


def test_import_zip_dedups_name(tmp_path):
    nb = _make_notebook(tmp_path)
    out_zip = tmp_path / "MyNotes.zip"
    export_zip(str(nb), str(out_zip))

    notebooks_dir = tmp_path / "notebooks"
    notebooks_dir.mkdir()
    assert import_zip(str(out_zip), str(notebooks_dir)) == "MyNotes"
    assert import_zip(str(out_zip), str(notebooks_dir)) == "MyNotes_1"
    assert import_zip(str(out_zip), str(notebooks_dir)) == "MyNotes_2"
    assert (notebooks_dir / "MyNotes_2" / "notes.txt").exists()


def test_import_zip_nested_layout_strips_prefix(tmp_path):
    # Zip with all files nested under a top-level folder (v1 handles both)
    out_zip = tmp_path / "Nested.zip"
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Nested/notes.txt", "hello nested")
        zf.writestr("Nested/attachments/foo.png", PNG_BYTES)

    notebooks_dir = tmp_path / "notebooks"
    notebooks_dir.mkdir()
    final = import_zip(str(out_zip), str(notebooks_dir))
    assert final == "Nested"
    assert (notebooks_dir / "Nested" / "notes.txt").read_text() == "hello nested"
    assert (notebooks_dir / "Nested" / "attachments" / "foo.png").exists()


def test_import_zip_creates_attachments_dir_when_missing(tmp_path):
    out_zip = tmp_path / "Flat.zip"
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("notes.txt", "just text")

    notebooks_dir = tmp_path / "notebooks"
    notebooks_dir.mkdir()
    final = import_zip(str(out_zip), str(notebooks_dir))
    assert (notebooks_dir / final / "attachments").is_dir()


# ── export_markdown ──────────────────────────────────────────────────────────

def test_export_markdown_conversions(tmp_path):
    nb = _make_notebook(tmp_path)
    attachments = nb / "attachments"
    content = (
        "# Title\n"
        "text [STRIKE]gone[/STRIKE] here\n"
        "[HL:green]hi[/HL] and [HL:yellow]ho[/HL]\n"
        "[IMAGE:foo.png:300]\n"
        "[IMAGE:foo.png]\n"
        "[FILE:doc.pdf]\n"
    )
    out_path = tmp_path / "exported.md"
    export_markdown(content, str(out_path), str(attachments), display_name_fn)

    md = out_path.read_text(encoding="utf-8")
    assert "~~gone~~" in md
    assert "==hi==" in md and "==ho==" in md
    # both width and no-width image forms convert identically
    assert md.count("![Foo Original.png](exported_attachments/foo.png)") == 2
    assert "[报告.pdf](exported_attachments/doc.pdf)" in md
    assert "[STRIKE]" not in md and "[HL:" not in md
    assert "__ATTACH_DIR__" not in md
    # referenced attachments copied next to the .md
    attach_out = tmp_path / "exported_attachments"
    assert (attach_out / "foo.png").read_bytes() == PNG_BYTES
    assert (attach_out / "doc.pdf").exists()


def test_export_markdown_no_attachments_dir_when_unreferenced(tmp_path):
    out_path = tmp_path / "plain.md"
    export_markdown("just **text**\n", str(out_path), str(tmp_path), display_name_fn)
    assert out_path.read_text(encoding="utf-8") == "just **text**\n"
    assert not (tmp_path / "plain_attachments").exists()


# ── content_to_html ──────────────────────────────────────────────────────────

def test_content_to_html_structure(tmp_path):
    nb = _make_notebook(tmp_path)
    attachments = nb / "attachments"
    content = (
        "# Big Title\n"
        "## Sub\n"
        "para with **bold** and *ital* and `code`\n"
        "> quoted\n"
        "- item one\n"
        "1. numbered\n"
        "- [ ] open task\n"
        "- [x] done task\n"
        "---\n"
        "```python\nprint('hi')\n```\n"
        "[STRIKE]struck[/STRIKE]\n"
        "[HL:green]glow[/HL]\n"
        "[IMAGE:foo.png:300]\n"
        "[IMAGE:missing.png]\n"
        "[FILE:doc.pdf]\n"
        "see https://ex.zz/a-b\n"
        "中文段落\n"
    )
    doc = content_to_html(content, "笔记 & Notes", str(attachments),
                          display_name_fn)

    assert doc.startswith("<!DOCTYPE html>\n<html>\n")
    assert "<title>笔记 &amp; Notes</title>" in doc
    assert "<h1>笔记 &amp; Notes</h1>" in doc
    assert "<h1>Big Title</h1>" in doc
    assert "<h2>Sub</h2>" in doc
    assert "<b>bold</b>" in doc
    assert "<i>ital</i>" in doc
    assert "<code>code</code>" in doc
    assert "<blockquote>quoted</blockquote>" in doc
    assert "<li>item one</li>" in doc
    assert "<ol>" in doc and "<li>numbered</li>" in doc
    assert '<input type="checkbox" disabled>' in doc
    assert '<input type="checkbox" disabled checked>' in doc
    assert '<span class="done">' in doc
    assert "<hr>" in doc
    assert "<pre><code>" in doc and "</code></pre>" in doc
    assert "print(&#x27;hi&#x27;)" in doc
    assert "<s>struck</s>" in doc
    assert '<mark class="hl-green">glow</mark>' in doc
    assert '<img src="data:image/png;base64,' in doc
    assert 'alt="Foo Original.png"' in doc
    assert 'width="300"' in doc
    # missing image keeps its (escaped) marker text
    assert "[IMAGE:missing.png]" in doc
    assert '<span class="file">📎 报告.pdf</span>' in doc
    # v1 quirk (ported verbatim): the inline URL regex writes &quot; inside a
    # character class, so URLs stop at any of & q u o t ; — e.g.
    # "https://example.com/x" is linked only up to "https://example.c".
    assert '<a href="https://ex.zz/a-b">https://ex.zz/a-b</a>' in doc
    assert content_to_html("see https://example.com/x", "T", str(attachments),
                           display_name_fn).count(
        '<a href="https://example.c">') == 1
    assert "<p>中文段落</p>" in doc


def test_content_to_html_custom_icon_fn(tmp_path):
    doc = content_to_html("[FILE:doc.pdf]", "T", str(tmp_path),
                          display_name_fn, icon_fn=lambda name: "¶")
    assert '<span class="file">¶ 报告.pdf</span>' in doc


def test_content_to_html_empty_content(tmp_path):
    doc = content_to_html("", "Empty", str(tmp_path), display_name_fn)
    assert "<h1>Empty</h1>" in doc
    assert doc.endswith("</main>\n</body>\n</html>\n")
