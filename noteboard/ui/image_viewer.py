"""Image viewer window (port of v1 open_image_viewer, ~L8558-8785).

QGraphicsView-based: wheel zoom toward the mouse, +/-/0 and Cmd/Ctrl
variants, Escape closes, left-drag pans, dark toolbar with live zoom %
and -/+/Reset buttons. Scale clamps to v1's 0.1-10.0 range in 1.25 steps.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import (QKeySequence, QPainter, QPixmap, QShortcut,
                           QTransform)
from PySide6.QtWidgets import (QGraphicsPixmapItem, QGraphicsScene,
                               QGraphicsView, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from noteboard.core.theme import THEMES

MIN_SCALE = 0.1
MAX_SCALE = 10.0
ZOOM_STEP = 1.25


class _ZoomView(QGraphicsView):
    """Pan with left-drag; wheel zooms toward the cursor."""

    def __init__(self, scene, viewer):
        super().__init__(scene)
        self._viewer = viewer
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta:
            self._viewer.zoom(delta > 0)
        event.accept()


class ImageViewer(QWidget):

    def __init__(self, path, display_name="", theme=None, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        t = theme or THEMES["dark"]
        title = display_name or path
        self.setWindowTitle(f"Image Viewer - {title}")

        self._scale = 1.0
        pixmap = QPixmap(path)
        self._pixmap = pixmap

        scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem(pixmap)
        self._item.setTransformationMode(
            Qt.TransformationMode.SmoothTransformation)
        scene.addItem(self._item)
        self._view = _ZoomView(scene, self)
        self._view.setStyleSheet(
            f"QGraphicsView {{ background-color: {t['viewer_canvas']};"
            f" border: none; }}")

        # Toolbar: zoom % label + -/+/Reset (v1's toolbar layout).
        toolbar = QWidget(self)
        toolbar.setFixedHeight(36)
        toolbar.setStyleSheet(
            f"background-color: {t['viewer_toolbar']};")
        self._zoom_label = QLabel("100%", toolbar)
        self._zoom_label.setStyleSheet(
            f"color: {t['fg']}; background: transparent;")
        self._zoom_label.setFixedWidth(52)

        def make_btn(text, slot):
            btn = QPushButton(text, toolbar)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {t['viewer_btn']};"
                f" color: white; border: none; border-radius: 4px;"
                f" padding: 4px 12px; font-weight: bold; }}"
                f"QPushButton:hover {{ background-color:"
                f" {t['viewer_btn_hover']}; }}")
            btn.clicked.connect(slot)
            return btn

        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(10, 0, 10, 0)
        bar.setSpacing(6)
        bar.addWidget(self._zoom_label)
        bar.addWidget(make_btn("-", lambda: self.zoom(False)))
        bar.addWidget(make_btn("+", lambda: self.zoom(True)))
        bar.addWidget(make_btn("Reset", self.reset_zoom))
        bar.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self._view, 1)

        # Shortcuts: Escape close; +/-/0 with and without Cmd/Ctrl (v1).
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(
            self.close)
        for seq in ("+", "=", "Ctrl++", "Ctrl+="):
            QShortcut(QKeySequence(seq), self).activated.connect(
                lambda: self.zoom(True))
        for seq in ("-", "_", "Ctrl+-"):
            QShortcut(QKeySequence(seq), self).activated.connect(
                lambda: self.zoom(False))
        for seq in ("0", "Ctrl+0"):
            QShortcut(QKeySequence(seq), self).activated.connect(
                self.reset_zoom)

        self._size_to_image(parent)

    def _size_to_image(self, parent):
        """v1: window = image + chrome, capped to screen-100, centered on
        the main window."""
        screen = (parent.screen() if parent is not None else None) \
            or self.screen()
        geo = screen.availableGeometry() if screen else None
        img_w = max(self._pixmap.width(), 200)
        img_h = max(self._pixmap.height(), 150)
        w = img_w + 40
        h = img_h + 80
        if geo is not None:
            w = min(w, geo.width() - 100)
            h = min(h, geo.height() - 100)
        self.resize(w, h)
        if parent is not None:
            pg = parent.geometry()
            x = max(0, pg.x() + (pg.width() - w) // 2)
            y = max(0, pg.y() + (pg.height() - h) // 2)
            self.move(x, y)

    # ── zoom ─────────────────────────────────────────────────────────────

    def zoom(self, zoom_in):
        scale = self._scale * ZOOM_STEP if zoom_in else self._scale / ZOOM_STEP
        self._set_scale(scale)

    def reset_zoom(self):
        self._set_scale(1.0)
        self._view.centerOn(self._item)

    def _set_scale(self, scale):
        self._scale = max(MIN_SCALE, min(MAX_SCALE, scale))
        self._view.setTransform(
            QTransform().scale(self._scale, self._scale))
        self._zoom_label.setText(f"{round(self._scale * 100)}%")
