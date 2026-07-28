"""Basic tests for the pure-logic noteboard.core modules (no Qt/Tk)."""

import os
import subprocess
import sys

from noteboard.core.i18n import I18N, Translator
from noteboard.core.syntax import tokenize
from noteboard.core.theme import HIGHLIGHT_NAMES, THEMES, blend
from noteboard.core.version import parse_version


# ── version ──────────────────────────────────────────────────────────

def test_parse_version_basic():
    assert parse_version("1.2.3") == (1, 2, 3)
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("V2.0.0") == (2, 0, 0)


def test_parse_version_unparseable_parts():
    assert parse_version("1.2b.x") == (1, 2, 0)
    assert parse_version("") == (0,)
    assert parse_version("  v1.10  ") == (1, 10)


def test_parse_version_ordering():
    assert parse_version("v2.0.0") > parse_version("1.9.9")


# ── i18n ─────────────────────────────────────────────────────────────

def test_i18n_values_are_two_tuples():
    for key, value in I18N.items():
        assert isinstance(value, tuple) and len(value) == 2, key
        assert all(isinstance(s, str) for s in value), key


def test_translator_zh_en():
    tr = Translator()
    assert tr.language == "zh"
    assert tr.tr("save_btn") == "保存"
    tr_en = Translator(language="en")
    assert tr_en.tr("save_btn") == "Save"


def test_translator_fallback():
    tr = Translator()
    assert tr.tr("no_such_key_xyz") == "no_such_key_xyz"
    assert Translator("en").tr("no_such_key_xyz") == "no_such_key_xyz"


def test_translator_toggle():
    tr = Translator()
    tr.toggle()
    assert tr.language == "en"
    assert tr.tr("cancel") == "Cancel"
    tr.toggle()
    assert tr.language == "zh"
    assert tr.tr("cancel") == "取消"


# ── theme ────────────────────────────────────────────────────────────

def test_themes_dark_light_same_keys():
    assert set(THEMES) == {"dark", "light"}
    assert set(THEMES["dark"]) == set(THEMES["light"])


def test_highlight_names():
    assert HIGHLIGHT_NAMES == ("green", "yellow", "red", "orange", "purple")
    for name in HIGHLIGHT_NAMES:
        assert f"hl_{name}" in THEMES["dark"]
        assert f"hl_{name}" in THEMES["light"]


def test_blend_midpoint():
    # v1 _blend rounds each channel: 0 + (255-0)*0.5 = 127.5 → 128 → "80"
    assert blend("#000000", "#ffffff", 0.5) == "#808080"


def test_blend_endpoints():
    assert blend("#123456", "#abcdef", 0) == "#123456"
    assert blend("#123456", "#abcdef", 1) == "#abcdef"


# ── syntax ───────────────────────────────────────────────────────────

def _kinds(line, lang):
    """Map token text -> kind for readable assertions."""
    return {line[s:e]: kind for s, e, kind in tokenize(line, lang)}


def test_tokenize_python_line():
    line = 'def f(x): return "str" + 42  # comment'
    spans = tokenize(line, "python")
    kinds = {line[s:e]: k for s, e, k in spans}
    assert kinds['def'] == "kw"
    assert kinds['return'] == "kw"
    assert kinds['"str"'] == "str"
    assert kinds['42'] == "num"
    assert kinds['# comment'] == "com"
    # Comment runs to end of line and nothing after it is tokenized
    com = [(s, e) for s, e, k in spans if k == "com"]
    assert com == [(line.index('#'), len(line))]


def test_tokenize_class_keyword():
    kinds = _kinds("class Foo: pass", "python")
    assert kinds["class"] == "kw"
    assert kinds["pass"] == "kw"
    assert "Foo" not in kinds


def test_tokenize_comment_marker_inside_string_ignored():
    line = 'x = "a # b"  # real'
    kinds = _kinds(line, "python")
    assert kinds['"a # b"'] == "str"
    assert kinds["# real"] == "com"


def test_tokenize_language_alias():
    kinds = _kinds("const x = 1;", "javascript")  # alias → js
    assert kinds["const"] == "kw"
    assert kinds["1"] == "num"


def test_tokenize_unknown_lang_and_blank():
    assert tokenize("   ", "python") == []
    # Unknown language: no keywords/comments, but strings/numbers still hit
    kinds = _kinds('foo "bar" 7', "nosuchlang")
    assert kinds == {'"bar"': "str", "7": "num"}


# ── purity guard ─────────────────────────────────────────────────────

def test_no_gui_modules_imported():
    """Importing noteboard.core must not pull in Tk or Qt.

    Runs in a clean subprocess because pytest plugins (e.g. pytest-qt)
    may pre-import PySide6 into this process.
    """
    code = (
        "import sys\n"
        "import noteboard.core.version, noteboard.core.paths, "
        "noteboard.core.i18n, noteboard.core.theme, "
        "noteboard.core.fonts, noteboard.core.syntax\n"
        "assert 'tkinter' not in sys.modules, 'tkinter leaked'\n"
        "assert 'PySide6' not in sys.modules, 'PySide6 leaked'\n"
    )
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.run([sys.executable, "-c", code], check=True, cwd=repo_root)
