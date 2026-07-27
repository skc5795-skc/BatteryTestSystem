"""Copperstone application header."""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap, QRegion
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from core.config import APP_NAME, APP_VERSION, COPPERSTONE_TEAL, LOGO_PATH


def build_logo(window, max_height: int = 44, white: bool = False):
    self = window
    if not os.path.exists(LOGO_PATH):
        return None
    try:
        logo_label = QLabel()
        pixmap = QPixmap(LOGO_PATH)
        if pixmap.isNull():
            return None

        # Trim transparent padding from the source logo before scaling.
        # This prevents a mathematically centred QLabel from looking
        # visually too high or too low inside the header.
        mask = pixmap.mask()
        if not mask.isNull():
            visible_bounds = QRegion(mask).boundingRect()
            if visible_bounds.isValid() and not visible_bounds.isEmpty():
                pixmap = pixmap.copy(visible_bounds)

        pixmap = pixmap.scaledToHeight(
            max_height, Qt.TransformationMode.SmoothTransformation
        )

        if white:
            tinted = QPixmap(pixmap.size())
            tinted.fill(Qt.GlobalColor.transparent)
            painter = QPainter(tinted)
            painter.drawPixmap(0, 0, pixmap)
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceIn
            )
            painter.fillRect(tinted.rect(), QColor("white"))
            painter.end()
            pixmap = tinted

        logo_label.setPixmap(pixmap)
        logo_label.setFixedSize(pixmap.size())
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setContentsMargins(0, 0, 0, 0)
        logo_label.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        return logo_label
    except Exception as e:
        print(f"Could not load logo: {e}")
        return None


def build_header(window):
    self = window
    """Build the Copperstone header.

    Layout:
    - left third intentionally blank;
    - Copperstone logo centred in the header;
    - application name and version at the lower right.
    """
    header = QFrame()
    header.setObjectName("appHeader")
    if isinstance(COPPERSTONE_TEAL, QColor):
        teal_color = COPPERSTONE_TEAL.name()
    else:
        teal_color = str(COPPERSTONE_TEAL)

    header.setStyleSheet(
        f"""
        QFrame#appHeader {{
            background-color: {teal_color};
            border-radius: 7px;
        }}
        """
    )
    header.setFixedHeight(100)

    # Three equal columns keep the company logo centred in the complete
    # header rather than centred only in the unused space beside the text.
    layout = QGridLayout(header)
    layout.setContentsMargins(18, 8, 18, 8)
    layout.setHorizontalSpacing(0)
    layout.setVerticalSpacing(0)
    layout.setColumnStretch(0, 1)
    layout.setColumnStretch(1, 1)
    layout.setColumnStretch(2, 1)

    # Column 0 is intentionally empty.
    left_spacer = QWidget()
    left_spacer.setStyleSheet("background:transparent;")
    layout.addWidget(left_spacer, 0, 0)

    # Company logo in the visual centre of the complete header.
    logo_widget = self._build_logo(max_height=80, white=True)
    if logo_widget:
        layout.addWidget(
            logo_widget,
            0,
            1,
            Qt.AlignmentFlag.AlignCenter,
        )

    # Product name and version at the bottom-right of the header.
    title = QLabel(f"{APP_NAME} v{APP_VERSION}")
    title_font = QFont(self.heading_font_family, 15)
    title_font.setBold(True)
    title.setFont(title_font)
    title.setStyleSheet("color:white; background:transparent;")
    title.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
    )

    layout.addWidget(
        title,
        0,
        2,
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
    )
    return header
