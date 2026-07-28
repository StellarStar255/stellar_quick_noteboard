#!/usr/bin/env python3
"""Editor stack benchmarks. Run offscreen:

    QT_QPA_PLATFORM=offscreen python3 scripts/bench_editor.py [names...]

Benchmarks (default: all):
  basic     - load / initial highlight / keystroke avg+max / serialize on a
              synthetic 5,000-line note (the original benchmark)
  scroll    - viewport render sweep top->bottom over a note with 30 real
              2400x1400 images (paint-time image scaling cost)
  storm     - decode storm: load() -> all image_loaded fired + repaints done
  wordcount - one word-count tick (serialize + strip + count) on 10k lines
  scan      - URL-preview rescan no-op pass + outline extraction on 10k lines
  cold      - cold import + window-show time (subprocess, image-heavy data)

Synthetic image data is cached in a temp dir (override with
NOTEBOARD_BENCH_DATA; regenerated when missing) so before/after runs
compare on identical inputs.
"""

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QEventLoop, QPoint
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication

from noteboard.core.fonts import mono_font, system_font
from noteboard.core.theme import HIGHLIGHT_NAMES, THEMES

TOTAL_LINES = 5000
KEYSTROKES = 100

IMG_COUNT = 30
IMG_W, IMG_H = 2400, 1400
SCROLL_STEPS = 40

BENCH_DATA = os.environ.get(
    "NOTEBOARD_BENCH_DATA",
    os.path.join(tempfile.gettempdir(), "noteboard_bench_data"))


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


# ── synthetic image workspace ────────────────────────────────────────────

def ensure_image_workspace():
    """30 real 2400x1400 PNGs + a note referencing them. Cached on disk."""
    attach = os.path.join(BENCH_DATA, "attachments")
    os.makedirs(attach, exist_ok=True)
    for i in range(IMG_COUNT):
        path = os.path.join(attach, f"img_{i:02d}.png")
        if os.path.exists(path):
            continue
        img = QImage(IMG_W, IMG_H, QImage.Format.Format_RGB32)
        grad = QLinearGradient(0, 0, IMG_W, IMG_H)
        grad.setColorAt(0.0, QColor.fromHsv((i * 37) % 360, 200, 220))
        grad.setColorAt(1.0, QColor.fromHsv((i * 91) % 360, 180, 90))
        p = QPainter(img)
        p.fillRect(img.rect(), grad)
        for r in range(0, IMG_H, 60):  # texture so PNG decode isn't trivial
            p.setPen(QColor.fromHsv((i * 53 + r) % 360, 255, 255))
            p.drawLine(0, r, IMG_W, (r * 7) % IMG_H)
        p.end()
        img.save(path, "PNG")
    return attach


def image_note_text():
    lines = []
    for i in range(IMG_COUNT):
        width = ":600" if i % 3 == 0 else ""
        lines.append(f"## section {i}")
        lines.append(f"[IMAGE:img_{i:02d}.png{width}]")
        for j in range(15):
            lines.append(f"paragraph {i}-{j} with some **bold** filler text")
    return "\n".join(lines) + "\n"


def make_editor(attach=None):
    from noteboard.ui.editor.document import MarkerDocument
    from noteboard.ui.editor.highlighter import MarkdownHighlighter
    from noteboard.ui.editor.note_edit import NoteTextEdit
    md = MarkerDocument(attachments_dir=attach)
    md.document.setDefaultFont(QFont(system_font(), 13))
    hl = MarkdownHighlighter(md.document, THEMES["dark"], 13, mono_font())
    editor = NoteTextEdit(md, hl)
    editor.resize(900, 700)
    return editor, md, hl


def image_counter(md):
    """Connect BEFORE load() so no image_loaded signal is missed."""
    seen = []
    md.image_loaded.connect(lambda name: seen.append(name))
    return seen


def wait_images(seen, count, timeout_s=60.0):
    """Spin the event loop until *count* image_loaded signals fired."""
    deadline = time.perf_counter() + timeout_s
    while len(seen) < count and time.perf_counter() < deadline:
        QCoreApplication.processEvents(
            QEventLoop.ProcessEventsFlag.AllEvents, 20)
    QCoreApplication.processEvents()
    return len(seen)


def row(label, value, unit="ms", note=""):
    print(f"{label:<34}{value:>10.1f} {unit}   {note}".rstrip())


# ── benchmarks ───────────────────────────────────────────────────────────

def bench_basic():
    text = generate()
    editor, doc, hl = make_editor()

    t0 = time.perf_counter()
    doc.load(text)
    load_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    hl.rehighlight()
    highlight_ms = (time.perf_counter() - t0) * 1000

    editor.show()
    QApplication.processEvents()  # flush layout + queued initial rehighlight

    middle = doc.document.findBlockByNumber(TOTAL_LINES // 2)
    cursor = editor.textCursor()
    cursor.setPosition(middle.position() + min(10, max(middle.length() - 1, 0)))
    editor.setTextCursor(cursor)
    QApplication.processEvents()

    times = []
    for _ in range(KEYSTROKES):
        t0 = time.perf_counter()
        editor.textCursor().insertText("x")
        QApplication.processEvents()
        times.append(time.perf_counter() - t0)
    avg_ms = sum(times) / len(times) * 1000
    max_ms = max(times) * 1000

    t0 = time.perf_counter()
    out = doc.serialize()
    serialize_ms = (time.perf_counter() - t0) * 1000
    assert out.replace("x", "") == text.replace("x", "")  # sanity

    print(f"[basic] {TOTAL_LINES} lines, {len(text)} chars, "
          f"{KEYSTROKES} keystrokes")
    row("load", load_ms)
    row("initial rehighlight", highlight_ms)
    row("keystroke avg", avg_ms, note="(target < 16 ms)")
    row("keystroke max", max_ms)
    row("serialize", serialize_ms)
    editor.deleteLater()


def bench_scroll():
    attach = ensure_image_workspace()
    editor, md, hl = make_editor(attach)
    editor.show()
    seen = image_counter(md)
    md.load(image_note_text())
    QApplication.processEvents()
    loaded = wait_images(seen, IMG_COUNT)
    assert loaded == IMG_COUNT, f"only {loaded}/{IMG_COUNT} images decoded"
    QApplication.processEvents()

    vsb = editor.verticalScrollBar()
    lo, hi = vsb.minimum(), vsb.maximum()
    print(f"[scroll] {IMG_COUNT} x {IMG_W}x{IMG_H} images, "
          f"{SCROLL_STEPS + 1} render steps")
    for dpr in (1.0, 2.0):  # 2.0 emulates a retina backing store
        target = QImage(int(editor.viewport().width() * dpr),
                        int(editor.viewport().height() * dpr),
                        QImage.Format.Format_ARGB32_Premultiplied)
        target.setDevicePixelRatio(dpr)
        step_times = []
        for i in range(SCROLL_STEPS + 1):
            vsb.setValue(lo + (hi - lo) * i // SCROLL_STEPS)
            QApplication.processEvents()
            t0 = time.perf_counter()
            target.fill(0)
            painter = QPainter(target)
            editor.viewport().render(painter, QPoint())
            painter.end()
            step_times.append(time.perf_counter() - t0)
        total_ms = sum(step_times) * 1000
        row(f"sweep total (dpr {dpr:.0f})", total_ms)
        row(f"render step avg (dpr {dpr:.0f})", total_ms / len(step_times),
            note="(frame budget 16 ms)")
        row(f"render step max (dpr {dpr:.0f})", max(step_times) * 1000)
    cache_mb = sum(img.sizeInBytes()
                   for img in md._loaded_images.values()) / 1e6
    row("resident image cache", cache_mb, unit="MB")
    editor.deleteLater()


def bench_storm():
    attach = ensure_image_workspace()
    editor, md, hl = make_editor(attach)
    editor.show()
    QApplication.processEvents()
    seen = image_counter(md)

    t0 = time.perf_counter()
    md.load(image_note_text())
    load_ms = (time.perf_counter() - t0) * 1000
    loaded = wait_images(seen, IMG_COUNT)
    settled_ms = (time.perf_counter() - t0) * 1000
    assert loaded == IMG_COUNT, f"only {loaded}/{IMG_COUNT} images decoded"
    # drain remaining repaints triggered by the decode swaps
    QApplication.processEvents()
    drained_ms = (time.perf_counter() - t0) * 1000

    print(f"[storm] load -> all {IMG_COUNT} decodes swapped in")
    row("load() (blocking)", load_ms)
    row("all image_loaded fired", settled_ms)
    row("repaints drained", drained_ms)
    editor.deleteLater()


def bench_wordcount():
    from noteboard.core.markers import strip_markers
    from noteboard.ui.main_window import _WC_RE
    editor, md, hl = make_editor()
    md.load(generate(10000))
    QApplication.processEvents()

    t0 = time.perf_counter()
    text = strip_markers(md.serialize())
    words = len(_WC_RE.findall(text))
    chars = len(text) - text.count("\n")
    tick_ms = (time.perf_counter() - t0) * 1000

    print(f"[wordcount] 10k lines ({words} words, {chars} chars)")
    row("word-count tick", tick_ms, note="(every 400 ms after edits)")
    editor.deleteLater()


def bench_scan():
    from noteboard.ui.editor.url_preview import UrlPreviewManager
    from noteboard.ui.outline_panel import HEADING_RE
    from noteboard.core.markers import MARKER_SPLIT_RE
    editor, md, hl = make_editor()
    md.load(generate(10000))
    QApplication.processEvents()
    upm = UrlPreviewManager(md, cache={}, fetcher=None)

    t0 = time.perf_counter()
    upm.rescan()
    rescan_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    doc = md.document
    headings = []
    block = doc.begin()
    while block.isValid():
        m = HEADING_RE.match(block.text())
        if m:
            headings.append((block.blockNumber(), len(m.group(2)),
                             MARKER_SPLIT_RE.sub("", m.group(3)).strip()))
        block = block.next()
    outline_ms = (time.perf_counter() - t0) * 1000

    print(f"[scan] 10k lines ({len(headings)} headings)")
    row("url-preview rescan (no-op)", rescan_ms, note="(1 s after last edit)")
    row("outline extraction", outline_ms, note="(300 ms after edits)")
    editor.deleteLater()


COLD_SCRIPT = r"""
import os, sys, time
t0 = time.perf_counter()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
from noteboard.core.storage import NoteStore
from noteboard.ui.main_window import MainWindow
app = QApplication([])
store = NoteStore(sys.argv[2])
win = MainWindow(store)
win.show()
app.processEvents()
shown = (time.perf_counter() - t0) * 1000
print(f"COLD_MS {shown:.1f}")
"""


def bench_cold():
    import json
    import shutil
    ensure_image_workspace()
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(BENCH_DATA, "cold_data")
    nb_dir = os.path.join(data_dir, "notebooks", "bench")
    if not os.path.exists(nb_dir):
        os.makedirs(nb_dir)
        shutil.copytree(os.path.join(BENCH_DATA, "attachments"),
                        os.path.join(nb_dir, "attachments"))
        with open(os.path.join(nb_dir, "notes.txt"), "w",
                  encoding="utf-8") as f:
            f.write(image_note_text())
    with open(os.path.join(data_dir, "config.json"), "w",
              encoding="utf-8") as f:
        json.dump({"current_notebook": "bench"}, f)

    script = os.path.join(BENCH_DATA, "_cold_probe.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(COLD_SCRIPT)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    samples = []
    for _ in range(3):
        out = subprocess.run([sys.executable, script, repo, data_dir],
                             capture_output=True, text=True, env=env,
                             timeout=120)
        for line in out.stdout.splitlines():
            if line.startswith("COLD_MS"):
                samples.append(float(line.split()[1]))
                break
        else:
            print(out.stdout)
            print(out.stderr)
            raise SystemExit("cold probe failed")
    print(f"[cold] import + MainWindow + show, image-heavy notebook "
          f"({len(samples)} runs)")
    row("best", min(samples))
    row("median", sorted(samples)[len(samples) // 2])


ALL = {"basic": bench_basic, "scroll": bench_scroll, "storm": bench_storm,
       "wordcount": bench_wordcount, "scan": bench_scan, "cold": bench_cold}


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("-")] or list(ALL)
    unknown = [n for n in names if n not in ALL]
    if unknown:
        raise SystemExit(f"unknown benchmark(s): {unknown}; "
                         f"choose from {list(ALL)}")
    app = QApplication.instance() or QApplication(sys.argv)
    for i, name in enumerate(names):
        if i:
            print("-" * 58)
        ALL[name]()
    app.processEvents()  # drain deleteLater of bench widgets
    return 0


if __name__ == "__main__":
    sys.exit(main())
