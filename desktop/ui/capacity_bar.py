"""Custom Copperstone capacity progress bar."""

import os

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import QProgressBar

from core.config import COPPERSTONE_GREEN
from desktop.ui.battery_theme import (
    COPPERSTONE_DARK_GREY,
    COPPERSTONE_LIGHT_GREY,
)


class CapacityProgressBar(QProgressBar):
    """Capacity indicator with a moving gear and the value below the bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._measured_ah = 0.0
        self._rated_ah = 0.0
        self._percent = 0.0
        self._gear_pixmap = self._load_capacity_gear()

        self.setRange(0, 1000)
        self.setValue(0)
        self.setTextVisible(False)

        # Upper area: progress track and gear. Lower area: capacity text.
        self.setMinimumHeight(54)
        self.setMaximumHeight(58)

    @staticmethod
    def _load_capacity_gear() -> QPixmap:
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        gear_path = os.path.join(project_root, "gear_watermark.png")
        pixmap = QPixmap(gear_path)
        if pixmap.isNull():
            print(f"Could not load capacity gear: {gear_path}")
        return pixmap

    def set_capacity(self, measured_ah: float, rated_ah: float) -> None:
        self._measured_ah = max(0.0, float(measured_ah or 0.0))
        self._rated_ah = max(0.0, float(rated_ah or 0.0))

        if self._rated_ah > 0:
            percentage = self._measured_ah / self._rated_ah * 100.0
            self._percent = max(0.0, min(100.0, percentage))
        else:
            self._percent = 0.0

        self.setValue(round(self._percent * 10))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        text_height = 18.0
        text_gap = 3.0
        bar_area_height = self.height() - text_height - text_gap
        track_height = 22.0

        bar_rect = QRectF(
            1.0,
            max(1.0, (bar_area_height - track_height) / 2.0),
            self.width() - 2.0,
            track_height,
        )
        radius = bar_rect.height() / 2.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COPPERSTONE_LIGHT_GREY))
        painter.drawRoundedRect(bar_rect, radius, radius)

        ratio = max(0.0, min(1.0, self._percent / 100.0))
        fill_width = bar_rect.width() * ratio

        if fill_width > 0:
            fill_rect = QRectF(
                bar_rect.left(),
                bar_rect.top(),
                max(fill_width, bar_rect.height()),
                bar_rect.height(),
            )
            fill_rect.setRight(min(fill_rect.right(), bar_rect.right()))
            painter.setBrush(QColor(COPPERSTONE_GREEN))
            painter.drawRoundedRect(fill_rect, radius, radius)

        gear_size = bar_rect.height() * 1.45
        gear_x = bar_rect.left() + gear_size / 2.0

        if fill_width > gear_size / 2.0:
            gear_x = bar_rect.left() + fill_width

        gear_x = max(
            bar_rect.left() + gear_size / 2.0,
            min(gear_x, bar_rect.right() - gear_size / 2.0),
        )

        gear_rect = QRectF(
            gear_x - gear_size / 2.0,
            bar_rect.center().y() - gear_size / 2.0,
            gear_size,
            gear_size,
        )

        if not self._gear_pixmap.isNull():
            painter.drawPixmap(
                gear_rect,
                self._gear_pixmap,
                QRectF(self._gear_pixmap.rect()),
            )

        if self._rated_ah > 0:
            text = (
                f"{self._measured_ah:.1f} / {self._rated_ah:.1f} Ah "
                f"({self._percent:.0f}%)"
            )
        else:
            text = "0.0 / 0.0 Ah (0%)"

        text_rect = QRectF(
            0.0,
            bar_area_height + text_gap,
            self.width(),
            text_height,
        )

        text_font = QFont(self.font())
        text_font.setBold(True)
        painter.setFont(text_font)
        painter.setPen(QColor(COPPERSTONE_DARK_GREY))
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
