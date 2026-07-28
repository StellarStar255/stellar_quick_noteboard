#!/usr/bin/env python3
"""Editor stack benchmark: load / highlight / keystroke / serialize timings
on a synthetic 5,000-line note. Run offscreen:

    QT_QPA_PLATFORM=offscreen python3 scripts/bench_editor.py
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QApplication

from noteboard.core.fonts import mono_font, system_font
from noteboard.core.theme import HIGHLIGHT_NAMES, THEMES
from noteboard.ui.editor.document import MarkerDocument
from noteboard.ui.editor.highlighter import MarkdownHighlighter
from noteboard.ui.editor.note_edit import NoteTextEdit

TOTAL_LINES = 5000
KEYSTROKES = 100


def generate(total=TOTAL_LINES):
    out = []
    while len(out) < total:
        k = len(out)
        c = k % 25
        if k % 100 == 0:
            out.append(f"[IMAGE:img_{k}.png:300]")  # 50 image placeholders
        elif c == 1:
            out.append(f"# Heading {k}")
        elif c == 2:
            out.append(f"## Sub heading {k} with **bold** words")
        elif c == 3:
            out.append(f"- list item {k} with *italic* text")
        elif c == 4:
            out.append(f"- [x] done task {k}")
        elif c == 5:
            out.append(f"- [ ] open task {k}")
        elif c == 6:
            color = HIGHLIGHT_NAMES[k % len(HIGHLIGHT_NAMES)]
            out.append(f"[HL:{color}]highlighted {k}[/HL] tail text")
        elif c == 7:
            out.append(f"[STRIKE]struck {k}[/STRIKE] plus `inline code`")
        elif c == 8:
            out.append(f"see https://example.com/page/{k}?q=1 for details")
        elif c == 9:
            out.extend(["```python",
                        f"def fn_{k}(x):  # comment",
                        f"    total = x * {k} + 0.5",
                        "    return 'val: ' + str(total)",
                        "```"])
        elif c == 16:
            out.extend(["```js",
                        f"// block {k}",
                        f"const v{k} = 'text' + {k};",
                        "```"])
        elif c == 20:
            out.append("> a quoted line with **bold** inside")
        else:
            out.append(f"plain paragraph line {k} mixing `code` and *italic*")
    return "\n".join(out[:total]) + "\n"


def main():
    app = QApplication(sys.argv)
    text = generate()

    doc = MarkerDocument()
    t0 = time.perf_counter()
    doc.load(text)
    load_ms = (time.perf_counter() - t0) * 1000

    hl = MarkdownHighlighter(doc.document, THEMES["dark"], 13, mono_font())
    doc.document.setDefaultFont(QFont(system_font(), 13))
    t0 = time.perf_counter()
    hl.rehighlight()
    highlight_ms = (time.perf_counter() - t0) * 1000

    editor = NoteTextEdit(doc, hl)
    editor.resize(900, 700)
    editor.show()
    app.processEvents()  # flush layout + Qt's queued initial rehighlight

    middle = doc.document.findBlockByNumber(TOTAL_LINES // 2)
    cursor = editor.textCursor()
    cursor.setPosition(middle.position() + min(10, max(middle.length() - 1, 0)))
    editor.setTextCursor(cursor)
    app.processEvents()

    times = []
    for _ in range(KEYSTROKES):
        t0 = time.perf_counter()
        editor.textCursor().insertText("x")
        app.processEvents()
        times.append(time.perf_counter() - t0)
    avg_ms = sum(times) / len(times) * 1000
    max_ms = max(times) * 1000

    t0 = time.perf_counter()
    out = doc.serialize()
    serialize_ms = (time.perf_counter() - t0) * 1000
    assert out.replace("x", "") == text.replace("x", "")  # sanity

    print(f"bench_editor: {TOTAL_LINES} lines, {len(text)} chars, "
          f"{KEYSTROKES} keystrokes")
    print("-" * 46)
    print(f"{'load':<28}{load_ms:>10.1f} ms")
    print(f"{'initial rehighlight':<28}{highlight_ms:>10.1f} ms")
    print(f"{'keystroke avg':<28}{avg_ms:>10.2f} ms   (target < 16 ms)")
    print(f"{'keystroke max':<28}{max_ms:>10.2f} ms")
    print(f"{'serialize':<28}{serialize_ms:>10.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
