"""Marker-dialect QTextDocument wrapper.

The document's plain text IS the notes.txt marker text verbatim, with one
exception: [IMAGE:name:width] / [IMAGE:name] / [FILE:name] markers become a
single U+FFFC object char carrying char-format properties. Every other
marker ([STRIKE], [HL:color], markdown syntax) stays literal text — the
highlighter styles it, so serialize() only has to re-emit object chars and
copy fragment text to round-trip byte-for-byte.
"""

import os

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import (QColor, QImage, QTextCharFormat, QTextCursor,
                           QTextDocument, QTextFormat, QTextImageFormat)

from noteboard.core.markers import (FILE_RE, IMAGE_RE, MARKER_SPLIT_RE,
                                    has_markers)

PROP_INTERNAL_NAME = QTextFormat.UserProperty + 1  # str, attachment filename
PROP_IMAGE_WIDTH = QTextFormat.UserProperty + 2    # int, 0 = no explicit width
PROP_FILE_LINK = QTextFormat.UserProperty + 3      # bool, marks a [FILE:] object
PROP_EPHEMERAL = QTextFormat.UserProperty + 4      # bool, skipped by serialize()

OBJECT_CHAR = "\ufffc"  # object replacement char backing image/file objects
LINE_SEP = "\u2028"     # QTextEdit soft line break (Shift+Return)


def _placeholder_image(color, size=48):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(QColor(color))
    return img


class MarkerDocument(QObject):
    """Wraps a QTextDocument whose text is the marker dialect verbatim."""

    def __init__(self, attachments_dir=None, parent=None):
        super().__init__(parent)
        self.attachments_dir = attachments_dir
        self.document = QTextDocument(self)

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
            for part in MARKER_SPLIT_RE.split(text):
                if not part:
                    continue
                m = IMAGE_RE.fullmatch(part)
                if m:
                    self._insert_image(cursor, m.group(1),
                                       int(m.group(2)) if m.group(2) else 0)
                    continue
                m = FILE_RE.fullmatch(part)
                if m:
                    self._insert_file(cursor, m.group(1))
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

    def _insert_image(self, cursor, name, width):
        fmt = QTextImageFormat()
        fmt.setName(f"attach://{name}")
        fmt.setProperty(PROP_INTERNAL_NAME, name)
        fmt.setProperty(PROP_IMAGE_WIDTH, width)
        img = None
        if self.attachments_dir:
            path = os.path.join(self.attachments_dir, name)
            if os.path.exists(path):
                img = QImage(path)
                if img.isNull():
                    img = None
        if img is None:
            # Missing/unreadable attachment: gray placeholder so layout works.
            img = _placeholder_image("#7d8590")
        self.document.addResource(QTextDocument.ResourceType.ImageResource,
                                  QUrl(f"attach://{name}"), img)
        if width > 0:
            fmt.setWidth(width)
            if img.width() > 0:
                fmt.setHeight(width * img.height() / img.width())
        # else: natural size (v1 default width cap comes in M3)
        cursor.insertImage(fmt)

    def _insert_file(self, cursor, name):
        # Rendered as an image object too (placeholder chip for M2; icon+name
        # in M3) — PROP_FILE_LINK on the format is what distinguishes it from
        # a real image in serialize().
        fmt = QTextImageFormat()
        fmt.setName(f"attachfile://{name}")
        fmt.setProperty(PROP_INTERNAL_NAME, name)
        fmt.setProperty(PROP_FILE_LINK, True)
        self.document.addResource(QTextDocument.ResourceType.ImageResource,
                                  QUrl(f"attachfile://{name}"),
                                  _placeholder_image("#58a6ff", 20))
        cursor.insertImage(fmt)

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
