"""Qt-side attachment helpers: import naming, async QImage loading, chips.

Naming scheme is copied verbatim from v1 (QuickNoteBoard.py):

- pasted clipboard images (paste_image ~L8175):
      ``img_{%Y%m%d_%H%M%S}_{uuid4[:8]}.png``
- imported files/directories (paste_files ~L8196):
      ``{base_name}_{%Y%m%d_%H%M%S}_{uuid4[:8]}{ext}``

The async loader decodes QImages on Qt's global thread pool and delivers
them back on the GUI thread via a queued signal, so the document can swap
placeholder resources without blocking load.
"""

import os
import shutil
import uuid
from datetime import datetime

from PySide6.QtCore import QObject, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QImage, QImageReader,
                           QPainter, QPen)

from noteboard.core.attachments import file_icon

# v1 paste_files image extension set (L8198)
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}


# ── v1 naming scheme ─────────────────────────────────────────────────────

def _stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S"), str(uuid.uuid4())[:8]


def pasted_image_name():
    """Internal filename for a pasted clipboard image (v1 paste_image)."""
    timestamp, unique_id = _stamp()
    return f"img_{timestamp}_{unique_id}.png"


def internal_file_name(original_name):
    """Internal filename for an imported file (v1 paste_files)."""
    timestamp, unique_id = _stamp()
    base_name, file_ext = os.path.splitext(original_name)
    return f"{base_name}_{timestamp}_{unique_id}{file_ext}"


def save_pasted_image(qimage, attachments_dir):
    """Save a clipboard QImage as PNG with v1's name; return internal name."""
    os.makedirs(attachments_dir, exist_ok=True)
    name = pasted_image_name()
    qimage.save(os.path.join(attachments_dir, name), "PNG")
    return name


def import_file(file_path, attachments_dir):
    """Copy *file_path* (file or directory) into *attachments_dir* under a
    v1 internal name. Returns (internal_name, original_name, original_path).
    v1: copytree for directories (.app bundles), copy2 for files."""
    os.makedirs(attachments_dir, exist_ok=True)
    original_name = os.path.basename(file_path.rstrip(os.sep))
    internal_name = internal_file_name(original_name)
    dest = os.path.join(attachments_dir, internal_name)
    if os.path.isdir(file_path):
        shutil.copytree(file_path, dest)
    else:
        shutil.copy2(file_path, dest)
    return internal_name, original_name, os.path.abspath(file_path)


def read_image_size(path):
    """Natural (width, height) from the image header without decoding the
    pixels; None when unreadable."""
    size = QImageReader(path).size()
    if size.isValid() and size.width() > 0 and size.height() > 0:
        return size.width(), size.height()
    return None


# ── file chip rendering ──────────────────────────────────────────────────

def file_chip_image(display_name, theme, font_family, font_size=13):
    """Render a pill-shaped chip QImage: file_icon(display_name) + name.

    Returns (image, logical_width, logical_height). Drawn at 2x with a
    device pixel ratio for crisp text on retina displays; theme-change
    regeneration is an M4 hook."""
    icon = file_icon(display_name)
    text = f"{icon}  {display_name}"
    font = QFont(font_family, font_size)
    metrics = QFontMetrics(font)
    pad_x, pad_y = 10, 4
    w = metrics.horizontalAdvance(text) + 2 * pad_x
    h = metrics.height() + 2 * pad_y

    dpr = 2.0
    img = QImage(int(w * dpr), int(h * dpr),
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    img.setDevicePixelRatio(dpr)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setBrush(QColor(theme["bg_tertiary"]))
    painter.setPen(QPen(QColor(theme["border"]), 1))
    radius = h / 2.0
    painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), radius, radius)
    painter.setFont(font)
    # v1 styles file-link text with accent_green (insert_file_link L8971)
    painter.setPen(QColor(theme["accent_green"]))
    painter.drawText(QRectF(pad_x, pad_y, w - 2 * pad_x, h - 2 * pad_y),
                     Qt.AlignmentFlag.AlignVCenter
                     | Qt.AlignmentFlag.AlignLeft, text)
    painter.end()
    return img, w, h


# ── async image loading ──────────────────────────────────────────────────

class _LoadTask(QRunnable):

    def __init__(self, loader, key, path):
        super().__init__()
        self._loader = loader
        self._key = key
        self._path = path

    def run(self):
        img = QImage(self._path)
        # Emitting from the worker thread: the connection to the loader's
        # GUI-thread slot is queued automatically; QImage is safely shared.
        try:
            self._loader._decoded.emit(self._key, img)
        except RuntimeError:
            pass  # loader (and its document) were deleted mid-decode


class ImageLoader(QObject):
    """Decodes QImages on the global thread pool; `loaded` fires on the
    GUI thread with (resource_key, image). Null images are dropped."""

    loaded = Signal(str, QImage)
    _decoded = Signal(str, QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending = set()
        self._decoded.connect(self._on_decoded)

    def request(self, key, path):
        if key in self._pending:
            return
        self._pending.add(key)
        QThreadPool.globalInstance().start(_LoadTask(self, key, path))

    def _on_decoded(self, key, img):
        self._pending.discard(key)
        if not img.isNull():
            self.loaded.emit(key, img)
