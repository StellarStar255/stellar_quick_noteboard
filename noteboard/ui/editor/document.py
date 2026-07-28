"""Marker-dialect QTextDocument wrapper.

The document's plain text IS the notes.txt marker text verbatim, with one
exception: [IMAGE:name:width] / [IMAGE:name] / [FILE:name] markers become a
single U+FFFC object char carrying char-format properties. Every other
marker ([STRIKE], [HL:color], markdown syntax) stays literal text — the
highlighter styles it, so serialize() only has to re-emit object chars and
copy fragment text to round-trip byte-for-byte.

M3 image pipeline:

- Real attachments load progressively: the document inserts a light
  placeholder resource immediately, with the image format's width/height
  fixed from the file header (QImageReader — no pixel decode), so layout
  never reflows; a thread-pool worker decodes the full QImage and swaps
  the resource on the GUI thread (`image_loaded` fires per name).
- Display width follows v1: explicit marker width wins, else
  min(natural width, config "image_width" [default 400]); clamped 50-800
  (v1 insert_image_at_cursor / _load_deferred_images).
- [FILE:name] renders as an icon+name chip image; video files with a
  cached ``_thumb_{name}.png`` render the thumbnail instead (v1
  _insert_video_preview), capped at min(image_width, 400).
- Like v1's save (get_content_with_markers skip ranges), the filename
  label line under images/video thumbs is EPHEMERAL: inserted at load
  when `config["show_image_name"]` is on, marked PROP_EPHEMERAL, and
  dropped (with its newline) by serialize().
"""

import os

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import (QColor, QImage, QTextCharFormat, QTextCursor,
                           QTextDocument, QTextFormat, QTextImageFormat)

from noteboard.core.attachments import is_video_file
from noteboard.core.fonts import system_font
from noteboard.core.markers import (FILE_RE, IMAGE_RE, MARKER_SPLIT_RE,
                                    has_markers)
from noteboard.core.theme import THEMES
from noteboard.ui.editor import attachments_ui

PROP_INTERNAL_NAME = QTextFormat.UserProperty + 1  # str, attachment filename
PROP_IMAGE_WIDTH = QTextFormat.UserProperty + 2    # int, 0 = no explicit width
PROP_FILE_LINK = QTextFormat.UserProperty + 3      # bool, marks a [FILE:] object
PROP_EPHEMERAL = QTextFormat.UserProperty + 4      # bool, skipped by serialize()

OBJECT_CHAR = "\ufffc"  # object replacement char backing image/file objects
LINE_SEP = "\u2028"     # QTextEdit soft line break (Shift+Return)

# v1 resize clamp (insert_image_at_cursor / on_image_drag)
MIN_IMAGE_WIDTH = 50
MAX_IMAGE_WIDTH = 800
DEFAULT_IMAGE_WIDTH = 400  # v1 max_image_width config default


PLACEHOLDER_SIZE = 48  # gray box for missing/undecoded attachments


def _placeholder_image(color, size=PLACEHOLDER_SIZE):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(QColor(color))
    return img


class MarkerDocument(QObject):
    """Wraps a QTextDocument whose text is the marker dialect verbatim."""

    #: emitted (internal name) when an async decode finished and the
    #: placeholder resource has been swapped for the real image.
    image_loaded = Signal(str)

    def __init__(self, attachments_dir=None, parent=None):
        super().__init__(parent)
        self.attachments_dir = attachments_dir
        self.document = QTextDocument(self)

        # App-provided wiring (spike defaults keep tests/bench standalone).
        self.config = {"image_width": DEFAULT_IMAGE_WIDTH,
                       "show_image_name": True}
        self.filename_map = {}       # internal name -> {"name","path"} | str
        self.attachment_saver = None  # callable(internal, original, path)
        self.theme = THEMES["dark"]
        self.ui_font_family = system_font()

        # Resource-key ("attach://x" / "attachfile://x") indexed caches.
        # _loaded_images protects decoded QImages/chips from GC.
        self._loaded_images = {}
        self._natural_sizes = {}
        self._loader = attachments_ui.ImageLoader(self)
        self._loader.loaded.connect(self._on_image_decoded)

    # ── small helpers ────────────────────────────────────────────────────

    def attachment_path(self, name):
        if not self.attachments_dir:
            return None
        return os.path.join(self.attachments_dir, name)

    def display_name(self, internal_name):
        """v1 get_display_name via filename_map (dict or legacy string)."""
        info = self.filename_map.get(internal_name)
        if isinstance(info, dict):
            return info.get("name", internal_name)
        if isinstance(info, str):
            return info
        return internal_name

    def show_image_name(self):
        return bool(self.config.get("show_image_name", True))

    def _config_width(self):
        try:
            return int(self.config.get("image_width", DEFAULT_IMAGE_WIDTH))
        except (TypeError, ValueError):
            return DEFAULT_IMAGE_WIDTH

    def natural_size(self, key):
        return self._natural_sizes.get(key)

    def display_size(self, key, marker_width):
        """(width, height) an image object renders at. Explicit marker
        width wins; else min(natural, config image_width); clamp 50-800."""
        nat = self._natural_sizes.get(key)
        if marker_width and marker_width > 0:
            w = marker_width
        elif nat:
            w = min(nat[0], self._config_width())
        else:
            w = self._config_width()
        w = max(MIN_IMAGE_WIDTH, min(MAX_IMAGE_WIDTH, w))
        if nat and nat[0] > 0:
            h = max(1, round(w * nat[1] / nat[0]))
        else:
            h = w
        return w, h

    # ── loading ──────────────────────────────────────────────────────────

    def load(self, text):
        doc = self.document
        # Disabling undo during the load both keeps it out of the stack and
        # clears any previous history.
        doc.setUndoRedoEnabled(False)
        doc.clear()
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        if not has_markers(text):
            cursor.insertText(text, QTextCharFormat())
        else:
            parts = [p for p in MARKER_SPLIT_RE.split(text) if p]
            for i, part in enumerate(parts):
                at_line_end = (i + 1 == len(parts)
                               or parts[i + 1].startswith("\n"))
                m = IMAGE_RE.fullmatch(part)
                if m:
                    name = m.group(1)
                    width = int(m.group(2)) if m.group(2) else 0
                    have_file = self._insert_image(cursor, name, width)
                    if have_file and at_line_end and self.show_image_name():
                        self._insert_label(cursor, self.display_name(name))
                    continue
                m = FILE_RE.fullmatch(part)
                if m:
                    name = m.group(1)
                    used_thumb = self._insert_file(cursor, name)
                    # v1 always shows the filename under a video preview.
                    if used_thumb and at_line_end:
                        self._insert_label(cursor, self.display_name(name))
                    continue
                # Styling markers and plain text stay verbatim. The explicit
                # empty format matters: without it the cursor inherits the
                # previous object's char format (its properties would leak
                # onto text and corrupt serialize()).
                cursor.insertText(part, QTextCharFormat())
        cursor.endEditBlock()
        doc.setUndoRedoEnabled(True)
        doc.clearUndoRedoStacks()
        doc.setModified(False)

    def _insert_label(self, cursor, text):
        """Ephemeral filename label on its own line (dropped by serialize,
        like v1's imgname_/file_ skip ranges in get_content_with_markers)."""
        cursor.insertText("\n", QTextCharFormat())
        fmt = QTextCharFormat()
        fmt.setProperty(PROP_EPHEMERAL, True)
        fmt.setForeground(QColor(self.theme["fg_dim"]))
        cursor.insertText(text, fmt)

    def insert_image_at(self, cursor, name, width=0, with_label=False):
        """Insert an [IMAGE] object at *cursor* (paste path)."""
        have_file = self._insert_image(cursor, name, width)
        if with_label and have_file and self.show_image_name():
            self._insert_label(cursor, self.display_name(name))

    def insert_file_at(self, cursor, name):
        """Insert a [FILE] object at *cursor* (paste path). Video files
        with a thumbnail also get an ephemeral name label (v1)."""
        used_thumb = self._insert_file(cursor, name)
        if used_thumb:
            self._insert_label(cursor, self.display_name(name))

    def register_image(self, name, qimage):
        """Seed the resource cache with an already-decoded image (used by
        paste so the just-saved bitmap needn't be re-decoded)."""
        key = f"attach://{name}"
        self._loaded_images[key] = qimage
        self._natural_sizes[key] = (qimage.width(), qimage.height())
        self.document.addResource(QTextDocument.ResourceType.ImageResource,
                                  QUrl(key), qimage)

    def _insert_image(self, cursor, name, width):
        """Insert the object char for [IMAGE:name(:width)]. Returns True
        when a real attachment backs it (placeholder+async or cached).

        The format ALWAYS gets explicit width/height: an unsized image
        object renders at the resource's natural pixel size, so the moment
        the shared resource key is swapped for the real decoded image
        (another fragment's async decode, register_image, ...) an unsized
        fragment would blow up far past MAX_IMAGE_WIDTH. When the natural
        size is unknown (missing file / unreadable header) the placeholder
        box size keeps today's rendering; _on_image_decoded corrects the
        geometry once a decode reveals the real size."""
        key = f"attach://{name}"
        fmt = QTextImageFormat()
        fmt.setName(key)
        fmt.setProperty(PROP_INTERNAL_NAME, name)
        fmt.setProperty(PROP_IMAGE_WIDTH, width)
        have_file = self._prepare_resource(key, self.attachment_path(name))
        if key in self._natural_sizes:
            w, h = self.display_size(key, width)
        else:
            w = h = PLACEHOLDER_SIZE  # size unknown: gray/light box
        fmt.setWidth(w)
        fmt.setHeight(h)
        cursor.insertImage(fmt)
        return have_file

    def _insert_file(self, cursor, name):
        """Insert the object char for [FILE:name] — video thumbnail when
        cached, icon+name chip otherwise. Returns True when the thumbnail
        was used. PROP_FILE_LINK is what distinguishes it from a real
        image in serialize()."""
        key = f"attachfile://{name}"
        fmt = QTextImageFormat()
        fmt.setName(key)
        fmt.setProperty(PROP_INTERNAL_NAME, name)
        fmt.setProperty(PROP_FILE_LINK, True)

        used_thumb = False
        if is_video_file(name) and self.attachments_dir:
            thumb_path = os.path.join(self.attachments_dir,
                                      f"_thumb_{name}.png")
            if (key in self._loaded_images or os.path.exists(thumb_path)) \
                    and self._prepare_resource(key, thumb_path):
                # v1 _load_deferred_images: min(max_image_width, 400)
                nat = self._natural_sizes.get(key)
                w = min(self._config_width(), DEFAULT_IMAGE_WIDTH)
                if nat:
                    w = min(w, nat[0])
                w = max(MIN_IMAGE_WIDTH, min(MAX_IMAGE_WIDTH, w))
                h = (max(1, round(w * nat[1] / nat[0])) if nat and nat[0]
                     else w)
                fmt.setWidth(w)
                fmt.setHeight(h)
                used_thumb = True

        if not used_thumb:
            chip = self._loaded_images.get(key)
            if chip is None:
                chip, w, h = attachments_ui.file_chip_image(
                    self.display_name(name), self.theme, self.ui_font_family)
                self._loaded_images[key] = chip
                self._natural_sizes[key] = (int(w), int(h))
            else:
                w, h = self._natural_sizes[key]
            self.document.addResource(
                QTextDocument.ResourceType.ImageResource, QUrl(key), chip)
            fmt.setWidth(w)
            fmt.setHeight(h)
        cursor.insertImage(fmt)
        return used_thumb

    def _prepare_resource(self, key, path):
        """Ensure a resource exists for *key*: reuse the decoded cache, or
        read the header for sizing, install a light placeholder and queue
        an async decode. False when the file is missing/unreadable (a gray
        box resource is installed so layout still works)."""
        doc = self.document
        cached = self._loaded_images.get(key)
        if cached is not None:
            doc.addResource(QTextDocument.ResourceType.ImageResource,
                            QUrl(key), cached)
            return True
        if path and os.path.exists(path):
            size = attachments_ui.read_image_size(path)
            if size:
                self._natural_sizes[key] = size
                # Object dimensions come from the char format, so a small
                # light fill is enough — no reflow when the real bits land.
                doc.addResource(
                    QTextDocument.ResourceType.ImageResource, QUrl(key),
                    _placeholder_image(self.theme["bg_tertiary"], 32))
                self._loader.request(key, path)
                return True
            # Header unreadable (partially-synced file, exotic format):
            # still try the full decode — _on_image_decoded sizes the
            # fragments once (if) it succeeds.
            self._loader.request(key, path)
        # Missing/unreadable attachment: gray placeholder so layout works.
        doc.addResource(QTextDocument.ResourceType.ImageResource,
                        QUrl(key), _placeholder_image("#7d8590"))
        return False

    def _on_image_decoded(self, key, img):
        """GUI-thread slot: swap the placeholder for the decoded image."""
        self._loaded_images[key] = img
        self._natural_sizes[key] = (img.width(), img.height())
        self.document.addResource(QTextDocument.ResourceType.ImageResource,
                                  QUrl(key), img)
        self._fix_fragment_sizes(key)
        self._refresh_fragments(key)
        self.image_loaded.emit(key.split("://", 1)[1])

    def _fix_fragment_sizes(self, key):
        """Safety net once the natural size of *key* is known: re-derive
        every fragment's display geometry and correct any that is unset or
        wrong (fragment inserted while the file was missing/unreadable, or
        an aspect ratio the header lied about). Normal fragments already
        match, so this edits nothing. Corrections join the previous undo
        step (like URL previews) instead of polluting undo with their own
        entry, and keep PROP_IMAGE_WIDTH untouched so serialize()
        round-trips byte-for-byte."""
        doc = self.document
        fixes = []  # (position, corrected QTextImageFormat)
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    cf = frag.charFormat()
                    if (cf.isImageFormat()
                            and cf.toImageFormat().name() == key
                            and cf.property(PROP_INTERNAL_NAME) is not None):
                        old = cf.toImageFormat()
                        marker_w = int(old.property(PROP_IMAGE_WIDTH) or 0)
                        w, h = self.display_size(key, marker_w)
                        if (abs(old.width() - w) >= 1
                                or abs(old.height() - h) >= 1):
                            fmt = QTextImageFormat(old)
                            fmt.setWidth(w)
                            fmt.setHeight(h)
                            for pos in range(frag.position(),
                                             frag.position() + frag.length()):
                                fixes.append((pos, fmt))
                it += 1
            block = block.next()
        if not fixes:
            return
        was_modified = doc.isModified()
        cursor = QTextCursor(doc)
        cursor.joinPreviousEditBlock()
        try:
            for pos, fmt in fixes:
                c = QTextCursor(doc)
                c.setPosition(pos)
                c.setPosition(pos + 1, QTextCursor.MoveMode.KeepAnchor)
                c.setCharFormat(fmt)
        finally:
            cursor.endEditBlock()
            doc.setModified(was_modified)

    def _refresh_fragments(self, key):
        """Repaint every object fragment using resource *key* (placeholder
        swap changes no geometry, so only those ranges are dirtied)."""
        doc = self.document
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    cf = frag.charFormat()
                    if (cf.isImageFormat()
                            and cf.toImageFormat().name() == key):
                        doc.markContentsDirty(frag.position(), frag.length())
                it += 1
            block = block.next()

    # ── resize (drag-edge path) ──────────────────────────────────────────

    def set_image_width(self, position, new_width, join=False):
        """Set an image object's display width (undoable; PROP_IMAGE_WIDTH
        is picked up by serialize()). *join* merges into the previous undo
        step so a whole drag collapses into one."""
        doc = self.document
        probe = QTextCursor(doc)
        probe.setPosition(position + 1)
        cf = probe.charFormat()  # format of the char AT `position`
        if not cf.isImageFormat() or cf.property(PROP_INTERNAL_NAME) is None:
            return False
        old = cf.toImageFormat()
        key = old.name()
        new_width = max(MIN_IMAGE_WIDTH, min(MAX_IMAGE_WIDTH, int(new_width)))

        fmt = QTextImageFormat(old)
        fmt.setProperty(PROP_IMAGE_WIDTH, new_width)
        fmt.setWidth(new_width)
        nat = self._natural_sizes.get(key)
        if nat and nat[0] > 0:
            fmt.setHeight(max(1, round(new_width * nat[1] / nat[0])))
        elif old.width() > 0 and old.height() > 0:
            fmt.setHeight(max(1, round(new_width * old.height()
                                       / old.width())))

        cursor = QTextCursor(doc)
        cursor.setPosition(position)
        cursor.setPosition(position + 1, QTextCursor.MoveMode.KeepAnchor)
        if join:
            cursor.joinPreviousEditBlock()
        else:
            cursor.beginEditBlock()
        cursor.setCharFormat(fmt)
        cursor.endEditBlock()
        return True

    # ── serialization ────────────────────────────────────────────────────

    def serialize(self):
        parts = []
        block = self.document.begin()
        while block.isValid():
            texts = []
            saw_fragment = False
            all_ephemeral = True
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    saw_fragment = True
                    cf = frag.charFormat()
                    if not cf.hasProperty(PROP_EPHEMERAL):
                        all_ephemeral = False
                        texts.append(self._fragment_text(frag, cf))
                it += 1
            if saw_fragment and all_ephemeral:
                # Wholly ephemeral block: skip its "\n" too by dropping the
                # entry entirely (blocks are joined with "\n" below).
                block = block.next()
                continue
            parts.append("".join(texts))
            block = block.next()
        return "\n".join(parts)

    @staticmethod
    def _fragment_text(frag, cf):
        text = frag.text()
        if cf.hasProperty(PROP_FILE_LINK):
            name = cf.property(PROP_INTERNAL_NAME)
            return f"[FILE:{name}]" * text.count(OBJECT_CHAR)
        if cf.isImageFormat():
            name = cf.property(PROP_INTERNAL_NAME)
            if name is None:
                return ""  # foreign image object, nothing we can emit
            width = int(cf.property(PROP_IMAGE_WIDTH) or 0)
            marker = (f"[IMAGE:{name}:{width}]" if width > 0
                      else f"[IMAGE:{name}]")
            return marker * text.count(OBJECT_CHAR)
        return text.replace(LINE_SEP, "\n").replace(OBJECT_CHAR, "")
