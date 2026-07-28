"""QSyntaxHighlighter port of v1's markdown/marker styling.

All visual styling lives here; the document char formats stay untouched
(except image/file objects), so the highlighter can restyle freely without
polluting undo history. Styles mirror v1's _update_markdown_tag_styles /
_configure_syntax_tags (QuickNoteBoard.py ~L5461-5533).

Block state is a bit-packed int carried between lines:
  bits 0-4  fence language id (index+1 into FENCE_LANGS, 0 = not in fence)
  bit  5    inside an open [STRIKE] span
  bits 6-8  open [HL:color] index+1 into HIGHLIGHT_NAMES (0 = none)
"""

from PySide6.QtGui import (QColor, QFont, QSyntaxHighlighter, QTextCharFormat)

from noteboard.core import syntax
from noteboard.core.markers import (HL_CLOSE, HL_OPEN_RE, MARKER_SPLIT_RE,
                                    STRIKE_CLOSE, STRIKE_OPEN, URL_RE,
                                    classify_line, inline_spans,
                                    strip_style_markers)
from noteboard.core.fonts import mono_font
from noteboard.core.theme import HIGHLIGHT_NAMES, blend

# id 1 = fence with no/unknown language; known languages get ids 2+.
FENCE_LANGS = ("",) + tuple(sorted(syntax.SYN_KEYWORDS))

# v1 heading size scales (L5471)
HEADING_SCALES = {"heading1": 1.6, "heading2": 1.35, "heading3": 1.15}

_FENCE_MASK = 0x1F
_STRIKE_BIT = 0x20
_HL_SHIFT = 6
_HL_MASK = 0x7


class MarkdownHighlighter(QSyntaxHighlighter):

    def __init__(self, document, theme_colors, base_font_size=12,
                 mono_family=None):
        super().__init__(document)
        self.cursor_block = -1
        self.base_font_size = base_font_size
        self.mono_family = mono_family or mono_font()
        self.colors = theme_colors
        self._build_formats()

    def set_theme(self, colors):
        self.colors = colors
        self._build_formats()
        self.rehighlight()

    # ── format table ─────────────────────────────────────────────────────

    def _build_formats(self):
        t = self.colors
        sz = self.base_font_size
        code_bg = QColor(blend(t["text_bg"], t["fg"], 0.07))
        f = {}

        def fmt(fg=None, bg=None, size=None, bold=False, italic=False,
                mono=False, strike=False, underline=False):
            c = QTextCharFormat()
            if fg:
                c.setForeground(QColor(fg))
            if bg:
                c.setBackground(bg if isinstance(bg, QColor) else QColor(bg))
            if size:
                c.setFontPointSize(size)
            if bold:
                c.setFontWeight(QFont.Weight.Bold)
            if italic:
                c.setFontItalic(True)
            if mono:
                c.setFontFamilies([self.mono_family])
            if strike:
                c.setFontStrikeOut(True)
            if underline:
                c.setFontUnderline(True)
            return c

        # Markers on the cursor's line are dimmed but readable; elsewhere
        # they collapse to a 1pt transparent sliver (v1's md_elide).
        f["marker_dim"] = fmt(fg=t["fg_dim"], size=sz)
        f["marker_collapsed"] = fmt(size=1)
        f["marker_collapsed"].setForeground(QColor(0, 0, 0, 0))

        for kind, scale in HEADING_SCALES.items():
            f[kind] = fmt(fg=t["fg"], size=int(sz * scale), bold=True)
        f["bold"] = fmt(fg=t["fg"], bold=True)
        f["italic"] = fmt(fg=t["fg"], italic=True)
        f["code"] = fmt(fg=t["fg"], bg=code_bg, mono=True)
        f["codeblock"] = fmt(fg=t["fg"], bg=code_bg, mono=True)
        f["fence"] = fmt(bg=code_bg, mono=True)
        f["quote_marker"] = fmt(fg=t["accent"])
        f["quote"] = fmt(fg=t["fg"], italic=True)
        f["list_marker"] = fmt(fg=t["accent"])
        f["task_box"] = fmt(fg=t["accent"], bold=True, mono=True)
        f["task_box_done"] = fmt(fg=t["accent_green"], bold=True, mono=True)
        f["task_done"] = fmt(fg=t["fg_dim"], strike=True)
        f["hr"] = fmt(fg=t["border"])
        f["nb_link"] = fmt(fg=t["accent"], underline=True)
        f["url"] = fmt(fg=t["accent_url"], underline=True)
        f["strike"] = fmt(fg=t["fg_dim"], strike=True)
        for name in HIGHLIGHT_NAMES:
            f["hl_" + name] = fmt(bg=t["hl_" + name])
        f["syn_kw"] = fmt(fg=t["accent"])
        f["syn_str"] = fmt(fg=t["accent_green"])
        f["syn_num"] = fmt(fg=t["hl_orange"])
        f["syn_com"] = fmt(fg=t["fg_placeholder"])
        self._fmt = f

    # ── per-block highlighting ───────────────────────────────────────────

    def highlightBlock(self, text):
        prev = self.previousBlockState()
        if prev < 0:
            prev = 0
        fence_id = prev & _FENCE_MASK
        in_strike = bool(prev & _STRIKE_BIT)
        hl_idx = (prev >> _HL_SHIFT) & _HL_MASK

        f = self._fmt
        marker = (f["marker_dim"]
                  if self.currentBlock().blockNumber() == self.cursor_block
                  else f["marker_collapsed"])
        n = len(text)
        ops = []  # (start, end, fmt) in application order; later wins on merge

        # Classify through [HL:]/[STRIKE] wrappers: a highlighted heading is
        # still a heading. Spans computed on the stripped view are projected
        # back onto raw columns via the index map.
        if fence_id > 0:
            stripped, imap = text, None
            info = classify_line(text, in_fence=True)
        else:
            stripped, imap = strip_style_markers(text)
            info = classify_line(stripped)
        kind = info.kind

        def mp(span):
            s, e = span
            if imap is None:
                return s, e
            if s >= e or not imap:
                return 0, 0
            return imap[s], imap[e - 1] + 1

        if kind == "code":
            ops.append((0, n, f["codeblock"]))
            for s, e, tok_kind in syntax.tokenize(text, FENCE_LANGS[fence_id - 1]):
                ops.append((s, e, f["syn_" + tok_kind]))
        elif kind in ("fence_open", "fence_close"):
            ops.append((0, n, f["fence"]))
            ops.append((0, n, marker))
            if kind == "fence_open":
                lang = syntax.normalize_lang(info.lang)
                fence_id = (FENCE_LANGS.index(lang) + 1
                            if lang in FENCE_LANGS else 1)
            else:
                fence_id = 0
        elif kind == "hr":
            ops.append((0, n, f["hr"]))
        else:
            if kind in ("heading1", "heading2", "heading3"):
                ts, te = mp(info.text_span)
                ms, me = mp(info.marker_span)
                ops.append((ts, te, f[kind]))
                ops.append((ms, me, marker))
            elif kind == "quote":
                ts, te = mp(info.text_span)
                ms, me = mp(info.marker_span)
                ops.append((ts, te, f["quote"]))
                ops.append((ms, me, f["quote_marker"]))
            elif kind in ("task", "task_done"):
                if kind == "task_done":
                    ts, te = mp(info.text_span)
                    ops.append((ts, te, f["task_done"]))
                ms, me = mp(info.marker_span)
                ops.append((ms, me,
                            f["task_box_done" if info.checked else "task_box"]))
            elif kind == "list":
                ms, me = mp(info.marker_span)
                ops.append((ms, me, f["list_marker"]))

            for sp in inline_spans(stripped):
                span_fmt = f.get(sp.kind)
                if span_fmt is not None:
                    ops.append((*mp((sp.start, sp.end)), span_fmt))
                if sp.kind != "nb_link":  # [[..]] brackets stay visible in v1
                    for a, b in sp.marker_spans:
                        ops.append((*mp((a, b)), marker))

        # [STRIKE]/[HL:] spans apply on any line (v1 consumes these markers
        # at load before markdown formatting, so they are fence-agnostic).
        strike_from = 0 if in_strike else None
        hl_from = 0 if hl_idx else None
        for m in MARKER_SPLIT_RE.finditer(text):
            tok = m.group(0)
            if tok == STRIKE_OPEN:
                if strike_from is None:
                    strike_from = m.end()
            elif tok == STRIKE_CLOSE:
                if strike_from is not None:
                    ops.append((strike_from, m.start(), f["strike"]))
                strike_from = None
            elif tok == HL_CLOSE:
                if hl_from is not None:
                    ops.append((hl_from, m.start(),
                                f["hl_" + HIGHLIGHT_NAMES[hl_idx - 1]]))
                hl_from = None
                hl_idx = 0
            else:
                hm = HL_OPEN_RE.fullmatch(tok)
                if hm is None:
                    # Unparsed [IMAGE:/[FILE: leftovers are plain text in v1.
                    continue
                if hl_from is not None:
                    ops.append((hl_from, m.start(),
                                f["hl_" + HIGHLIGHT_NAMES[hl_idx - 1]]))
                name = hm.group(1)
                if name in HIGHLIGHT_NAMES:
                    hl_idx = HIGHLIGHT_NAMES.index(name) + 1
                    hl_from = m.end()
                else:
                    hl_idx = 0
                    hl_from = None
            ops.append((m.start(), m.end(), marker))
        if strike_from is not None:
            ops.append((strike_from, n, f["strike"]))
        if hl_from is not None:
            ops.append((hl_from, n, f["hl_" + HIGHLIGHT_NAMES[hl_idx - 1]]))

        for m in URL_RE.finditer(text):
            ops.append((m.start(), m.end(), f["url"]))

        self._apply_ops(ops)
        self.setCurrentBlockState(fence_id
                                  | (_STRIKE_BIT if strike_from is not None else 0)
                                  | (hl_idx << _HL_SHIFT))

    def _apply_ops(self, ops):
        """Apply overlapping (start, end, fmt) spans.

        QSyntaxHighlighter.setFormat overwrites instead of merging, so split
        the line at every span boundary and merge covering formats in
        application order. Op counts per line are small, so the quadratic
        scan stays O(line length)."""
        if not ops:
            return
        bounds = sorted({p for s, e, _ in ops for p in (s, e)})
        for a, b in zip(bounds, bounds[1:]):
            covering = [g for s, e, g in ops if s <= a and b <= e]
            if not covering:
                continue
            if len(covering) == 1:
                self.setFormat(a, b - a, covering[0])
                continue
            merged = QTextCharFormat(covering[0])
            for g in covering[1:]:
                for pid, val in g.properties().items():
                    merged.setProperty(pid, val)
            self.setFormat(a, b - a, merged)
