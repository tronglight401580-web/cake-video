from __future__ import annotations
import time
from pathlib import Path
from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget
from ..core.recipe import Recipe
from ..styles import load_style

class PreviewView(QWidget):
    """Shows graded vs original with a draggable split line (or either one alone)."""

    def __init__(self):
        super().__init__()
        self.graded: QImage | None = None
        self.original: QImage | None = None
        self.split = 0.5
        self.mode = "split"            # split | effect | original
        self.setMinimumSize(360, 360)
        self.setMouseTracking(True)

    def set_images(self, graded: QImage, original: QImage):
        self.graded, self.original = graded, original
        self.update()

    def _target(self) -> QRectF:
        img = self.graded or self.original
        if img is None:
            return QRectF(self.rect())
        k = min(self.width() / img.width(), self.height() / img.height())
        w, h = img.width() * k, img.height() * k
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101113"))
        if self.graded is None:
            p.setPen(QColor("#6b6f76"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "把视频拖进来，或点左侧「添加视频」")
            return
        r = self._target()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.mode == "original":
            p.drawImage(r, self.original)
        elif self.mode == "effect":
            p.drawImage(r, self.graded)
        else:
            sx = r.left() + r.width() * self.split
            iw = self.graded.width()
            src_split = iw * self.split
            p.drawImage(QRectF(r.left(), r.top(), sx - r.left(), r.height()), self.original,
                        QRectF(0, 0, src_split, self.original.height()))
            p.drawImage(QRectF(sx, r.top(), r.right() - sx, r.height()), self.graded,
                        QRectF(src_split, 0, iw - src_split, self.graded.height()))
            p.setPen(QPen(QColor(255, 255, 255, 220), 2))
            p.drawLine(QPointF(sx, r.top()), QPointF(sx, r.bottom()))
            p.setBrush(QColor(255, 255, 255, 230))
            p.drawEllipse(QPointF(sx, r.center().y()), 9, 9)
            f = QFont(self.font())
            f.setPointSize(10)
            p.setFont(f)
            for text, x, align in (("原片", r.left() + 10, Qt.AlignmentFlag.AlignLeft),
                                   ("效果", r.right() - 70, Qt.AlignmentFlag.AlignRight)):
                box = QRectF(x, r.top() + 10, 60, 22)
                p.fillRect(box, QColor(0, 0, 0, 140))
                p.setPen(QColor("white"))
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _drag(self, x: float):
        r = self._target()
        if r.width() > 0:
            self.split = min(1.0, max(0.0, (x - r.left()) / r.width()))
            self.update()

    def mousePressEvent(self, e):
        if self.mode == "split" and self.graded is not None:
            self._drag(e.position().x())

    def mouseMoveEvent(self, e):
        if self.mode == "split" and e.buttons() & Qt.MouseButton.LeftButton:
            self._drag(e.position().x())
