"""Maker-only background choices. Customer package colors stay independent."""
from .qt import *

THEMES = [
    ("dark", "深色", "#242830", "#151A22"),
    ("pink", "粉色", "#DC7586", "#2D1820"),
    ("yellow", "黄色", "#EAC15A", "#2A2418"),
    ("blue", "蓝色", "#83ADF2", "#101D2E"),
    ("green", "绿色", "#7CC9A4", "#10271F"),
    ("cyan", "青色", "#70C2D2", "#10262D"),
    ("purple", "紫色", "#B49BE5", "#221B30"),
    ("white", "白色", "#FFFFFF", "#F4F7FC"),
]


class ColorSwatch(QToolButton):
    def __init__(self, name, color, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.setToolTip(name)
        self.setAccessibleName(name)
        self.setCheckable(True)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self.color)
        painter.setPen(QPen(QColor("#8295AD"), 1))
        painter.drawEllipse(QRectF(4, 4, 16, 16))
        if self.isChecked():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#A8C9F7"), 2))
            painter.drawEllipse(QRectF(1, 1, 22, 22))
            pen = QPen(QColor("#173553") if self.color.lightness() > 140 else QColor("#FFFFFF"), 2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline(QPolygonF([QPointF(8, 12), QPointF(11, 15), QPointF(17, 8)]))
