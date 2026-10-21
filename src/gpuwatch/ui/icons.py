from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

STATE_COLORS = {
    "connected": "#2e7d32",
    "gray": "#546e7a",
    "error": "#c62828",
}

TRAY_SIZES = (16, 20, 24, 32, 48, 64)
APP_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _draw_chip(size: int, color: str, badge: bool) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    margin = size * 0.09
    body = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    radius = size * 0.2
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(body, radius, radius)

    painter.setBrush(QColor(255, 255, 255, 80))
    bar_height = max(1.2, body.height() * 0.1)
    for row in range(3):
        top = body.top() + body.height() * (0.26 + row * 0.2)
        bar = QRectF(
            body.left() + body.width() * 0.23,
            top,
            body.width() * 0.54,
            bar_height,
        )
        painter.drawRoundedRect(bar, bar_height / 2, bar_height / 2)

    if badge:
        radius = max(2.2, size * 0.17)
        center = QPointF(size - radius - size * 0.03, radius + size * 0.03)
        painter.setPen(QPen(QColor("#ffffff"), max(1.0, size * 0.035)))
        painter.setBrush(QColor("#ff6d00"))
        painter.drawEllipse(center, radius, radius)

    painter.end()
    return pixmap


@lru_cache(maxsize=32)
def tray_icon(state: str = "connected", badge: bool = False) -> QIcon:
    color = STATE_COLORS.get(state, STATE_COLORS["connected"])
    icon = QIcon()
    for size in TRAY_SIZES:
        icon.addPixmap(_draw_chip(size, color, badge))
    return icon


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    icon = QIcon()
    for size in APP_SIZES:
        icon.addPixmap(_draw_chip(size, STATE_COLORS["connected"], False))
    return icon
