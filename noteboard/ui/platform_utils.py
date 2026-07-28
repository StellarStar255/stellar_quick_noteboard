"""OS integration helpers: file manager reveal, default apps, clipboard.

Port of v1's platform glue (QuickNoteBoard.py):

- reveal_in_file_manager   <- reveal_in_finder (L9249): macOS ``open -R``,
  Windows ``explorer /select,``, Linux xdg-open on the directory.
- open_with_default_app    <- open_file (L9297): QDesktopServices covers
  all three platforms.
- copy_file_to_clipboard   <- copy_file_to_clipboard (L9113): Qt-native
  QMimeData with file urls + text fallback, replacing v1's osascript /
  PowerShell shell-outs. Verified on macOS: Qt puts «class furl»
  (public.file-url) on NSPasteboard, so Finder paste works without the
  osascript fallback.
- copy_text                <- clipboard_clear/append pairs.
- strikethrough_html + copy_rich_with_strikethrough
                           <- copy_with_strikethrough_rtf (L7423): the RTF
  osascript becomes text/html on the clipboard, with the same #888888
  strike color.
- launch_installer         <- _launch_update (L4480).
"""

import html as _html
import os
import platform
import subprocess

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtWidgets import QApplication

from noteboard.core.markers import (FILE_RE, HL_CLOSE, HL_OPEN_RE, IMAGE_RE,
                                    MARKER_SPLIT_RE, STRIKE_CLOSE,
                                    STRIKE_OPEN)

# v1 copy_file_to_clipboard L9129: extensions that also get bitmap data on
# the clipboard so image paste works in web/apps.
IMAGE_CLIP_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp'}

STRIKE_COLOR = "#888888"  # v1 RTF colortbl red136 green136 blue136


def reveal_in_file_manager(path):
    """Reveal *path* in Finder/Explorer/file manager (v1 reveal_in_finder).

    Returns False when the path doesn't exist (caller grays the menu item
    out beforehand; this is just the belt to that suspenders)."""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return False
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", "-R", path])
        elif system == "Windows":
            subprocess.run(["explorer", "/select,", path])
        else:
            subprocess.run(["xdg-open", os.path.dirname(path)])
    except Exception as e:
        print(f"Error revealing file: {e}")
        return False
    return True


def open_with_default_app(path):
    """Open *path* (file or directory) with the default application
    (v1 open_file; QDesktopServices covers macOS/Windows/Linux)."""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def file_mime_data(path, text=None):
    """QMimeData carrying *path* as a file url + text fallback; image
    files also get bitmap data (v1's NSImage+NSURL writeObjects)."""
    path = os.path.abspath(path)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    mime.setText(text if text is not None else path)
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_CLIP_EXTS and os.path.isfile(path):
        img = QImage(path)
        if not img.isNull():
            mime.setImageData(img)
    return mime


def copy_file_to_clipboard(path, text=None):
    """Copy the file at *path* to the clipboard so it can be pasted in
    Finder/Explorer and other apps (v1 copy_file_to_clipboard, without
    the osascript/PowerShell shell-outs — Qt file urls register as a
    real file copy on all three platforms).

    *text*, when given, replaces the plain-text fallback (v1's
    internal_marker piggyback)."""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return False
    QApplication.clipboard().setMimeData(file_mime_data(path, text))
    return True


def copy_text(text):
    """Plain text to the clipboard (v1 clipboard_clear + clipboard_append)."""
    QApplication.clipboard().setText(text)


def strikethrough_html(marker_text):
    """Simple HTML for marker text: [STRIKE] spans become
    ``<s style="color:#888888">``, other markers are dropped
    (v1 copy_with_strikethrough_rtf's RTF, as text/html)."""
    out = []
    strike = False
    for part in MARKER_SPLIT_RE.split(marker_text):
        if not part:
            continue
        if part == STRIKE_OPEN:
            strike = True
            continue
        if part == STRIKE_CLOSE:
            strike = False
            continue
        if part == HL_CLOSE or HL_OPEN_RE.fullmatch(part):
            continue
        if IMAGE_RE.fullmatch(part) or FILE_RE.fullmatch(part):
            continue
        esc = _html.escape(part).replace("\n", "<br>")
        if strike:
            out.append(f'<s style="color:{STRIKE_COLOR}">{esc}</s>')
        else:
            out.append(esc)
    return "<html><body>" + "".join(out) + "</body></html>"


def copy_rich_with_strikethrough(plain, html):
    """Put *plain* + *html* on the clipboard (replaces v1's RTF via
    osascript — text/html is understood by the same rich-text targets)."""
    mime = QMimeData()
    mime.setText(plain)
    mime.setHtml(html)
    QApplication.clipboard().setMimeData(mime)


def launch_installer(path):
    """Hand a downloaded installer to the OS (v1 _launch_update L4486):
    Windows os.startfile, macOS ``open``, Linux xdg-open. Raises on
    failure — the update flow surfaces the error dialog."""
    system = platform.system()
    if system == "Windows":
        os.startfile(path)  # noqa: attribute exists on Windows only
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
