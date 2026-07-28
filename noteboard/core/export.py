"""Pure notebook export/import logic ported from v1 (QuickNoteBoard.py).

Byte-faithful ports of:
- export_notebook (zip)            ~L3100-3129
- import_notebook                  ~L3145-3195
- export_notebook_markdown         ~L3216-3264
- _inline_md_to_html               ~L3290-3297
- _convert_content_to_html         ~L3299-3432

Instance state used by the v1 methods has been parameterized:
- self.get_attachments_path()  -> attachments_dir argument
- self.get_display_name        -> display_name_fn argument
- self.current_notebook        -> title argument (HTML) / caller (markdown)
- self.get_notebooks_list()    -> existing directories under notebooks_dir
- self.attachments_dir         -> attachments_dirname argument ("attachments")
The v1 HTML converter hardcodes the paperclip emoji for [FILE:] spans;
content_to_html takes an optional icon_fn (default returns that same emoji)
so the UI layer can substitute Linux-safe glyphs. It does NOT use self.tr
or theme colors — the CSS is a fixed light-theme stylesheet.

No Qt/Tk imports allowed in this module.
"""

import base64
import html
import os
import re
import shutil
import zipfile


def _atomic_write_text(path, content):
    """Write text to *path* atomically (private copy of v1 helper, L128-144)."""
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def export_zip(notebook_dir, out_path):
    """Export a notebook directory as a .zip file (v1 export_notebook core)."""
    if not os.path.isdir(notebook_dir):
        return
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(notebook_dir):
            for fn in filenames:
                abs_file = os.path.join(dirpath, fn)
                arc_name = os.path.relpath(abs_file, notebook_dir)
                zf.write(abs_file, arc_name)


def import_zip(zip_path, notebooks_dir, attachments_dirname="attachments"):
    """Import a notebook from a .zip file (v1 import_notebook core).

    Returns the final notebook name (deduplicated with _1, _2, ... when a
    notebook of that name already exists). Handles both flat (notes.txt at
    zip root) and nested (single top folder) layouts, exactly like v1.
    """
    with zipfile.ZipFile(zip_path, 'r') as zf:
        names = zf.namelist()
        # Determine notebook name from zip filename
        nb_name = os.path.splitext(os.path.basename(zip_path))[0]

        # If notebook already exists, append a number
        existing = set()
        if os.path.isdir(notebooks_dir):
            existing = {d for d in os.listdir(notebooks_dir)
                        if os.path.isdir(os.path.join(notebooks_dir, d))}
        base_name = nb_name
        counter = 1
        while nb_name in existing:
            nb_name = f"{base_name}_{counter}"
            counter += 1

        nb_path = os.path.join(notebooks_dir, nb_name)
        os.makedirs(nb_path, exist_ok=True)

        # Extract — handle both flat (notes.txt at root) and nested layouts
        # Check if files are inside a subdirectory
        has_subdir = all('/' in n for n in names if n and not n.endswith('/'))
        if has_subdir:
            # Files are nested under a folder, strip the common prefix
            prefix = os.path.commonpath([n for n in names if not n.endswith('/')])
            for member in names:
                if member.endswith('/'):
                    continue
                rel = os.path.relpath(member, prefix)
                target = os.path.join(nb_path, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(member) as src, open(target, 'wb') as dst:
                    dst.write(src.read())
        else:
            zf.extractall(nb_path)

        # Ensure attachments dir exists
        attach_dir = os.path.join(nb_path, attachments_dirname)
        os.makedirs(attach_dir, exist_ok=True)

    return nb_name


def export_markdown(content, out_path, attachments_dir, display_name_fn):
    """Export note content (with markers) as a standard .md file
    (v1 export_notebook_markdown core). Referenced attachments are copied to
    a sibling "<name>_attachments" folder and links point there."""
    used_files = []

    def img_repl(m):
        fn = m.group(1)
        used_files.append(fn)
        name = display_name_fn(fn)
        return f"![{name}](__ATTACH_DIR__/{fn})"

    def file_repl(m):
        fn = m.group(1)
        used_files.append(fn)
        name = display_name_fn(fn)
        return f"[{name}](__ATTACH_DIR__/{fn})"

    md = re.sub(r'\[IMAGE:([^:\]]+)(?::\d+)?\]', img_repl, content)
    md = re.sub(r'\[FILE:([^\]]+)\]', file_repl, md)
    md = md.replace('[STRIKE]', '~~').replace('[/STRIKE]', '~~')
    md = re.sub(r'\[HL:\w+\]', '==', md).replace('[/HL]', '==')

    if used_files:
        base = os.path.splitext(os.path.basename(out_path))[0]
        attach_dirname = f"{base}_attachments"
        attach_dir = os.path.join(os.path.dirname(out_path), attach_dirname)
        os.makedirs(attach_dir, exist_ok=True)
        src_dir = attachments_dir
        for fn in set(used_files):
            src = os.path.join(src_dir, fn)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(attach_dir, fn))
        md = md.replace("__ATTACH_DIR__", attach_dirname)

    _atomic_write_text(out_path, md)


def _inline_md_to_html(s):
    """Convert inline markdown (code, bold, italic, URLs) in an
    already-HTML-escaped string. (v1 _inline_md_to_html, verbatim.)"""
    s = re.sub(r'(?<!`)`([^`]+)`(?!`)', r'<code>\1</code>', s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', s)
    s = re.sub(r'(https?://[^\s<>&quot;]+)', r'<a href="\1">\1</a>', s)
    return s


def _default_icon_fn(display_name):
    """v1 hardcodes the paperclip for [FILE:] spans in HTML export."""
    return '📎'


def content_to_html(content, title, attachments_dir, display_name_fn,
                    icon_fn=_default_icon_fn):
    """Render note content (with markers) to a standalone HTML document.
    (v1 _convert_content_to_html, byte-faithful with default icon_fn.)"""
    attach_dir = attachments_dir

    esc = html.escape(content)

    # Inline-span markers → HTML
    esc = esc.replace('[STRIKE]', '<s>').replace('[/STRIKE]', '</s>')
    esc = re.sub(r'\[HL:(\w+)\]', r'<mark class="hl-\1">', esc)
    esc = esc.replace('[/HL]', '</mark>')

    def img_repl(m):
        fn, width = m.group(1), m.group(2)
        path = os.path.join(attach_dir, fn)
        if not os.path.exists(path):
            return m.group(0)
        ext = os.path.splitext(fn)[1].lower().lstrip('.')
        mime = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png', 'gif': 'gif',
                'webp': 'webp', 'bmp': 'bmp'}.get(ext, 'png')
        try:
            with open(path, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('ascii')
        except OSError:
            return m.group(0)
        w = f' width="{width}"' if width else ''
        alt = html.escape(display_name_fn(fn), quote=True)
        return f'<img src="data:image/{mime};base64,{b64}" alt="{alt}"{w}>'

    esc = re.sub(r'\[IMAGE:([^:\]]+)(?::(\d+))?\]', img_repl, esc)
    esc = re.sub(
        r'\[FILE:([^\]]+)\]',
        lambda m: (f'<span class="file">{icon_fn(display_name_fn(m.group(1)))} '
                   f'{html.escape(display_name_fn(m.group(1)))}</span>'),
        esc)

    out = []
    in_code = False
    list_mode = [None]  # None | 'ul' | 'ol'

    def close_list():
        if list_mode[0]:
            out.append(f"</{list_mode[0]}>")
            list_mode[0] = None

    def open_list(kind):
        if list_mode[0] != kind:
            close_list()
            out.append(f"<{kind}>")
            list_mode[0] = kind

    for line in esc.split('\n'):
        stripped = line.strip()
        if stripped.startswith('```'):
            close_list()
            out.append('</code></pre>' if in_code else '<pre><code>')
            in_code = not in_code
            continue
        if in_code:
            out.append(line)
            continue
        if (len(stripped) >= 3
                and re.match(r'^([-*_])\s*\1\s*\1[\s\-*_]*$', stripped)):
            close_list()
            out.append('<hr>')
            continue
        h = re.match(r'^(#{1,3})\s+(.+)', line)
        if h:
            close_list()
            lvl = len(h.group(1))
            out.append(f'<h{lvl}>{_inline_md_to_html(h.group(2))}</h{lvl}>')
            continue
        bq = re.match(r'^&gt;\s?(.*)', line)  # '>' is escaped at this point
        if bq:
            close_list()
            out.append(f'<blockquote>{_inline_md_to_html(bq.group(1))}</blockquote>')
            continue
        task = re.match(r'^\s*[-*] \[([ xX])\]\s?(.*)', line)
        if task:
            open_list('ul')
            checked = ' checked' if task.group(1) in 'xX' else ''
            cls = ' class="done"' if checked else ''
            out.append(f'<li class="task"><input type="checkbox" disabled{checked}> '
                       f'<span{cls}>{_inline_md_to_html(task.group(2))}</span></li>')
            continue
        li = re.match(r'^\s*[-*]\s+(.*)', line)
        if li:
            open_list('ul')
            out.append(f'<li>{_inline_md_to_html(li.group(1))}</li>')
            continue
        ol = re.match(r'^\s*(\d+)\.\s+(.*)', line)
        if ol:
            open_list('ol')
            out.append(f'<li>{_inline_md_to_html(ol.group(2))}</li>')
            continue
        close_list()
        if stripped:
            out.append(f'<p>{_inline_md_to_html(line)}</p>')

    if in_code:
        out.append('</code></pre>')
    close_list()

    css = """
body { margin: 0; background: #f6f8fa; color: #1f2328;
       font: 16px/1.65 -apple-system, 'Segoe UI', 'Noto Sans CJK SC', sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 40px 24px;
       background: #ffffff; min-height: 100vh; box-sizing: border-box; }
h1, h2, h3 { line-height: 1.3; }
img { max-width: 100%; height: auto; border-radius: 6px; }
pre { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px;
      padding: 12px; overflow-x: auto; }
code { font-family: Menlo, Consolas, monospace; font-size: 0.9em;
       background: #f0f1f3; border-radius: 4px; padding: 1px 4px; }
pre code { background: none; padding: 0; }
blockquote { margin: 0; padding: 2px 14px; border-left: 4px solid #d0d7de;
             color: #57606a; }
p { margin: 6px 0; }
hr { border: none; border-top: 2px solid #d8dee4; margin: 18px 0; }
a { color: #0969da; }
.file { color: #1a7f37; }
li.task { list-style: none; margin-left: -20px; }
li.task .done { color: #8b949e; text-decoration: line-through; }
mark.hl-green  { background: #aceebb; }
mark.hl-yellow { background: #fff8c5; }
mark.hl-red    { background: #ffcecb; }
mark.hl-orange { background: #ffd8b5; }
mark.hl-purple { background: #e6d4f7; }
"""
    title = html.escape(title)
    body = "\n".join(out)
    return ("<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
            f"<title>{title}</title>\n<style>{css}</style>\n</head>\n"
            f"<body>\n<main>\n<h1>{title}</h1>\n{body}\n</main>\n</body>\n</html>\n")
