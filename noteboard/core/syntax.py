"""Lightweight code-block syntax highlighting (stdlib only, no GUI).

Port of v1's _highlight_code_line tokenization into a pure function:
tokenize() returns (start, end, kind) spans instead of tagging a Tk
Text widget.
"""

import re

SYN_KEYWORDS = {
    'python': frozenset(("def class return if elif else for while in not and or is "
                         "None True False import from as with try except finally "
                         "raise lambda yield global nonlocal pass break continue "
                         "del assert async await self match case").split()),
    'js': frozenset(("function var let const return if else for while do switch "
                     "case break continue new delete typeof instanceof in of class "
                     "extends super this null undefined true false import export "
                     "from default try catch finally throw async await yield "
                     "static get set void").split()),
    'c': frozenset(("int char long short float double void unsigned signed struct "
                    "union enum typedef static const return if else for while do "
                    "switch case break continue sizeof goto extern volatile inline "
                    "bool true false NULL nullptr class public private protected "
                    "virtual template typename namespace using new delete auto "
                    "final override package boolean String byte implements extends "
                    "interface abstract synchronized throws throw try catch finally "
                    "import this super instanceof").split()),
    'go': frozenset(("func package import var const type struct interface map chan "
                     "go defer return if else for range switch case break continue "
                     "select fallthrough goto nil true false make new len cap "
                     "append string int bool byte rune error").split()),
    'rust': frozenset(("fn let mut const static struct enum impl trait for while "
                       "loop if else match return use mod pub crate self super "
                       "where async await move ref dyn Box Vec Some None Ok Err "
                       "true false String str u8 u32 u64 i32 i64 f32 f64 usize "
                       "bool unsafe").split()),
    'shell': frozenset(("if then else elif fi for while do done case esac function "
                        "return exit echo export local read source set unset shift "
                        "break continue in").split()),
    'sql': frozenset(("select from where insert into values update set delete "
                      "create table drop alter index join left right inner outer "
                      "on group by order having limit offset union all distinct "
                      "as and or not null primary key foreign references "
                      "SELECT FROM WHERE INSERT INTO VALUES UPDATE SET DELETE "
                      "CREATE TABLE DROP ALTER INDEX JOIN LEFT RIGHT INNER OUTER "
                      "ON GROUP BY ORDER HAVING LIMIT OFFSET UNION ALL DISTINCT "
                      "AS AND OR NOT NULL PRIMARY KEY FOREIGN REFERENCES").split()),
    'json': frozenset("true false null".split()),
    'ruby': frozenset(("def end class module if elsif else unless while until for "
                       "in do return yield begin rescue ensure raise require puts "
                       "nil true false self super lambda proc attr_accessor "
                       "attr_reader").split()),
    'swift': frozenset(("func var let class struct enum protocol extension if else "
                        "guard switch case for while repeat return import nil true "
                        "false self super init deinit throws try catch defer where "
                        "as is in inout lazy weak static public private internal "
                        "open final override mutating").split()),
}

SYN_ALIASES = {
    'py': 'python', 'python3': 'python',
    'javascript': 'js', 'ts': 'js', 'typescript': 'js', 'jsx': 'js',
    'tsx': 'js', 'node': 'js',
    'c++': 'c', 'cpp': 'c', 'cc': 'c', 'h': 'c', 'hpp': 'c', 'java': 'c',
    'cs': 'c', 'c#': 'c', 'kotlin': 'c', 'kt': 'c', 'objc': 'c',
    'golang': 'go',
    'rs': 'rust',
    'sh': 'shell', 'bash': 'shell', 'zsh': 'shell',
    'rb': 'ruby',
    'mysql': 'sql', 'postgres': 'sql', 'postgresql': 'sql', 'sqlite': 'sql',
}

COMMENT_PREFIXES = {
    'python': '#', 'shell': '#', 'ruby': '#',
    'js': '//', 'c': '//', 'go': '//', 'rust': '//', 'swift': '//',
    'sql': '--', 'json': None,
}

_SYN_STR_RE = re.compile(
    r'"(?:[^"\\]|\\.)*"'
    r"|'(?:[^'\\]|\\.)*'"
    r'|`[^`]*`')
_SYN_TOKEN_RE = re.compile(
    r'(?P<str>"(?:[^"\\]|\\.)*"'
    r"|'(?:[^'\\]|\\.)*'"
    r'|`[^`]*`)'
    r'|(?P<word>[A-Za-z_][A-Za-z0-9_]*)'
    r'|(?P<num>\b\d+(?:\.\d+)?\b)')


def normalize_lang(lang):
    """Map a fence language alias (e.g. 'javascript') to its keyword-set key."""
    return SYN_ALIASES.get(lang, lang)


def tokenize(line, lang):
    """Tokenize one line inside a ``` code block and return spans to tag:
    a list of (start, end, kind) with kind in {"kw", "str", "num", "com"}.
    Line-based by design (multi-line strings are not tracked) — good
    enough for note-sized snippets."""
    if not line.strip():
        return []
    lang = SYN_ALIASES.get(lang, lang)
    keywords = SYN_KEYWORDS.get(lang, frozenset())
    comment_marker = COMMENT_PREFIXES.get(lang)

    spans = []

    # Comment start = first marker occurrence outside any string literal
    comment_start = None
    if comment_marker:
        string_spans = [(m.start(), m.end()) for m in _SYN_STR_RE.finditer(line)]
        pos = 0
        while True:
            pos = line.find(comment_marker, pos)
            if pos == -1:
                break
            if any(s <= pos < e for s, e in string_spans):
                pos += 1
                continue
            comment_start = pos
            break
    if comment_start is not None:
        spans.append((comment_start, len(line), "com"))
    limit = comment_start if comment_start is not None else len(line)

    for m in _SYN_TOKEN_RE.finditer(line, 0, limit):
        kind = m.lastgroup
        if kind == 'str':
            spans.append((m.start(), m.end(), "str"))
        elif kind == 'num':
            spans.append((m.start(), m.end(), "num"))
        elif kind == 'word' and m.group() in keywords:
            spans.append((m.start(), m.end(), "kw"))
    return spans
