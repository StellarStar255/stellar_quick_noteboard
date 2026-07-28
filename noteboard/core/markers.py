"""Pure-logic marker and markdown dialect for Stellar Quick Noteboard.

Every regex/format here is copied VERBATIM from the v1 Tkinter app
(QuickNoteBoard.py) so that v2 parses/emits the exact same dialect:

- IMAGE_RE / FILE_RE / HL_OPEN_RE     -> load_content_with_images (~L3840-3842)
- MARKER_SPLIT_RE                     -> load_content_with_images (~L3845)
- URL_RE                              -> self.url_pattern (~L594)
- NOTEBOOK_LINK_RE                    -> _apply_inline_markdown (~L5891)
- INTERNAL_LINK_RE / INTERNAL_RICH_RE -> paste handlers (~L7970, ~L8098)
- HEADING_RE / QUOTE_RE / TASK_RE / LIST_RE / HR_RE / fence handling
                                      -> apply_markdown_formatting (~L5690-5776)
- CODE_INLINE_RE / BOLD_RE / ITALIC_RE-> _apply_inline_markdown (~L5838-5873)

No Qt/Tk imports allowed in this module.
"""

import re
from dataclasses import dataclass, field

# ── Marker dialect (storage format) ──────────────────────────────────────────

# [IMAGE:filename] or [IMAGE:filename:width]   (v1 L3840)
IMAGE_RE = re.compile(r'\[IMAGE:([^:\]]+)(?::(\d+))?\]')
# [FILE:filename]                              (v1 L3841)
FILE_RE = re.compile(r'\[FILE:([^\]]+)\]')
# [HL:color]                                   (v1 L3842)
HL_OPEN_RE = re.compile(r'\[HL:(\w+)\]')
HL_CLOSE = '[/HL]'
STRIKE_OPEN = '[STRIKE]'
STRIKE_CLOSE = '[/STRIKE]'

# Highlight color names emitted by v1 (L502)
HIGHLIGHT_NAMES = ("green", "yellow", "red", "orange", "purple")

# Split pattern keeping the markers                (v1 L3845)
MARKER_SPLIT_RE = re.compile(
    r'(\[IMAGE:[^\]]+\]|\[FILE:[^\]]+\]|\[STRIKE\]|\[/STRIKE\]|\[HL:\w+\]|\[/HL\])')

# [[notebook name]] internal wiki-style link       (v1 L5891)
NOTEBOOK_LINK_RE = re.compile(r'\[\[([^\]]+)\]\]')

# [INTERNAL:type:filename] clipboard marker. v1 parses this by string slicing
# (marker_text[10:-1] then split(':', 1) — L8098-8103); this regex is the
# equivalent: type is everything up to the first ':', filename is the rest.
INTERNAL_LINK_RE = re.compile(r'^\[INTERNAL:([^:\]]+):(.+)\]$', re.DOTALL)

# [INTERNAL:RICH:notebook]...[/INTERNAL:RICH] clipboard marker (v1 L7970)
INTERNAL_RICH_RE = re.compile(
    r'^\[INTERNAL:RICH:([^\]]*)\](.*)\[/INTERNAL:RICH\]$', re.DOTALL)

# URL detection                                    (v1 L594-597)
URL_RE = re.compile(
    r'(https?://[^\s<>"{}|\\^`\[\]]+)',
    re.IGNORECASE
)

# ── Markdown line dialect ────────────────────────────────────────────────────

# Headings: # ## ###                               (v1 L5715)
HEADING_RE = re.compile(r'^(#{1,3})\s+(.+)')
# Block quote: > text                              (v1 L5731)
QUOTE_RE = re.compile(r'^(>)\s?(.*)')
# Task list: - [ ] todo / - [x] done               (v1 L5746)
TASK_RE = re.compile(r'^(\s*)([-*]) \[([ xX])\](\s?)(.*)')
# List markers: - , * , 1. (space after marker optional before non-ASCII)
#                                                  (v1 L5763)
LIST_RE = re.compile(r'^(\s*)([-*]|\d+\.)(?:\s|(?=[^\x00-\x7F]))')
# Horizontal rule: --- or ___ or *** (v1 L5709; note: inside the character
# class "\1" is chr(1), not a backreference — verbatim v1 behavior, so only
# exactly three markers separated by optional whitespace match).
# v1 additionally requires len(line.strip()) >= 3 — classify_line enforces it.
HR_RE = re.compile(r'^[ ]{0,3}([-*_])\s*\1\s*\1[\s\1]*$')
# Code fence. v1 detects fences with line.lstrip().startswith("```") and
# takes the language as stripped[3:].strip().lower() (L5690-5698).
FENCE_RE = re.compile(r'^(\s*)```(.*)$')

# ── Inline markdown dialect ──────────────────────────────────────────────────

# Inline code: `code`                              (v1 L5838)
CODE_INLINE_RE = re.compile(r'(?<!`)`(?!`)(.+?)(?<!`)`(?!`)')
# Bold: **text**                                   (v1 L5855)
BOLD_RE = re.compile(r'\*\*(.+?)\*\*')
# Italic: *text* (but not ** which is bold)        (v1 L5873)
ITALIC_RE = re.compile(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)')


@dataclass
class LineInfo:
    """Classification of a single markdown line (v1 apply_markdown_formatting).

    kind: one of "heading1", "heading2", "heading3", "list", "task",
          "task_done", "quote", "fence_open", "fence_close", "hr",
          "code" (line inside an open fence), "plain".
    indent: leading-whitespace count for list/task lines (else 0).
    lang: fence language for "fence_open" (lowercased; "" if none).
    checked: True for "task_done", False for "task", None otherwise.
    marker_span: (start, end) column span of the structural marker
                 (heading hashes incl. trailing space, quote '>', task
                 checkbox through ']', list bullet), or None.
    text_span: (start, end) column span of the content text, or None.
    """
    kind: str
    indent: int = 0
    lang: str = ""
    checked: bool = None
    marker_span: tuple = None
    text_span: tuple = None


def classify_line(line, in_fence=False):
    """Classify one line exactly as v1's apply_markdown_formatting does.

    ``in_fence`` carries the caller's code-block state: v1 toggles
    ``in_code_block`` on each fence line and skips block parsing inside.
    """
    # Code block fence (v1 L5690-5699)
    stripped = line.lstrip()
    if stripped.startswith("```"):
        indent = len(line) - len(stripped)
        if in_fence:
            return LineInfo(kind="fence_close", indent=indent,
                            marker_span=(indent, len(line)))
        lang = stripped[3:].strip().lower()
        return LineInfo(kind="fence_open", indent=indent, lang=lang,
                        marker_span=(indent, len(line)))

    # Inside code block (v1 L5702-5706)
    if in_fence:
        return LineInfo(kind="code")

    # Horizontal rule (v1 L5709)
    if HR_RE.match(line) and len(line.strip()) >= 3:
        return LineInfo(kind="hr")

    # Headings: # ## ### (v1 L5715-5728)
    h_match = HEADING_RE.match(line)
    if h_match:
        level = len(h_match.group(1))
        text_start_col = h_match.start(2)
        return LineInfo(kind=f"heading{level}",
                        marker_span=(0, text_start_col),  # include space after #
                        text_span=(text_start_col, len(line)))

    # Block quote: > text (v1 L5731-5743)
    bq_match = QUOTE_RE.match(line)
    if bq_match:
        return LineInfo(kind="quote",
                        marker_span=(0, 1),
                        text_span=(bq_match.start(2), len(line)))

    # Task list (checked before plain lists) (v1 L5746-5760)
    task_match = TASK_RE.match(line)
    if task_match:
        indent = len(task_match.group(1))
        state = task_match.group(3)
        done = state in 'xX'
        return LineInfo(kind="task_done" if done else "task",
                        indent=indent,
                        checked=done,
                        marker_span=(indent, task_match.end(3) + 1),  # through ']'
                        text_span=(task_match.start(5), len(line)))

    # List markers: - , * , 1. , 2. (v1 L5763-5773)
    list_match = LIST_RE.match(line)
    if list_match:
        indent = len(list_match.group(1))
        marker = list_match.group(2)
        return LineInfo(kind="list",
                        indent=indent,
                        marker_span=(indent, indent + len(marker)))

    return LineInfo(kind="plain")


@dataclass
class InlineSpan:
    """One inline markdown span found by inline_spans().

    kind: "code", "bold", "italic" or "nb_link".
    start/end: full span including markers.
    marker_spans: [(open_start, open_end), (close_start, close_end)].
    text: the interior text (group 1 of the v1 regex).
    """
    start: int
    end: int
    kind: str
    marker_spans: list = field(default_factory=list)
    text: str = ""


def inline_spans(line):
    """Scan a line for inline spans with v1 precedence/protection rules
    (_apply_inline_markdown, L5830-5912): inline code is matched first and
    its regions protect their interior — bold/italic/notebook links that
    overlap a code region are skipped. Bold and italic may both match
    (v1 applies them independently)."""
    spans = []
    code_regions = []

    # Inline code: `code`
    for m in CODE_INLINE_RE.finditer(line):
        spans.append(InlineSpan(
            start=m.start(), end=m.end(), kind="code",
            marker_spans=[(m.start(), m.start() + 1), (m.end() - 1, m.end())],
            text=m.group(1)))
        code_regions.append((m.start(), m.end()))

    # Bold: **text**
    for m in BOLD_RE.finditer(line):
        if any(m.start() < ce and m.end() > cs for cs, ce in code_regions):
            continue
        spans.append(InlineSpan(
            start=m.start(), end=m.end(), kind="bold",
            marker_spans=[(m.start(), m.start() + 2), (m.end() - 2, m.end())],
            text=m.group(1)))

    # Italic: *text* (but not ** which is bold)
    for m in ITALIC_RE.finditer(line):
        if any(m.start() < ce and m.end() > cs for cs, ce in code_regions):
            continue
        spans.append(InlineSpan(
            start=m.start(), end=m.end(), kind="italic",
            marker_spans=[(m.start(), m.start() + 1), (m.end() - 1, m.end())],
            text=m.group(1)))

    # Notebook links: [[notebook_name]]
    for m in NOTEBOOK_LINK_RE.finditer(line):
        if any(m.start() < ce and m.end() > cs for cs, ce in code_regions):
            continue
        spans.append(InlineSpan(
            start=m.start(), end=m.end(), kind="nb_link",
            marker_spans=[(m.start(), m.start() + 2), (m.end() - 2, m.end())],
            text=m.group(1)))

    return spans


def has_markers(text):
    """True when the content contains any storage markers.

    Inverse of v1's fast-path check in load_content_with_images (L3833),
    copied verbatim."""
    return not ('[IMAGE:' not in text and '[FILE:' not in text
                and '[STRIKE]' not in text and '[HL:' not in text)


def strip_markers(text):
    """Render marker content as plain text (for copy-as-plain / word count).

    Follows v1's load_content_with_images split (L3845): styling markers
    ([STRIKE], [/STRIKE], [HL:color], [/HL]) are dropped; [IMAGE:...] and
    [FILE:...] markers carry no visible text and are removed."""
    if not has_markers(text):
        return text
    out = []
    for part in MARKER_SPLIT_RE.split(text):
        if not part:
            continue
        if part in (STRIKE_OPEN, STRIKE_CLOSE, HL_CLOSE):
            continue
        if HL_OPEN_RE.fullmatch(part):
            continue
        if IMAGE_RE.fullmatch(part) or FILE_RE.fullmatch(part):
            continue
        out.append(part)
    return "".join(out)


# Only the styling wrappers — [IMAGE:]/[FILE:] become object chars at load,
# so they are not part of a line's textual structure.
STYLE_MARKER_RE = re.compile(r"\[STRIKE\]|\[/STRIKE\]|\[HL:\w+\]|\[/HL\]")


def strip_style_markers(text):
    """Remove [STRIKE]/[HL:] wrapper tokens from *text*.

    Returns (stripped, index_map) where index_map[i] is the original index
    of stripped[i]. Line classification must look through these wrappers —
    a highlighted heading is still a heading — and callers use the map to
    project spans computed on the stripped view back onto the raw line."""
    out = []
    imap = []
    pos = 0
    for m in STYLE_MARKER_RE.finditer(text):
        out.append(text[pos:m.start()])
        imap.extend(range(pos, m.start()))
        pos = m.end()
    out.append(text[pos:])
    imap.extend(range(pos, len(text)))
    return "".join(out), imap
