"""Copperstone application header."""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from core.config import APP_NAME, APP_VERSION, COPPERSTONE_TEAL, LOGO_PATH


def build_logo(window, max_height: int = 44):
    """Load and prepare the Copperstone logo."""

    if not os.path.exists(LOGO_PATH):
        print(f"Logo file not found: {LOGO_PATH}")
        return None

    try:
        pixmap = QPixmap(LOGO_PATH)

        if pixmap.isNull():
            print(f"Could not load logo image: {LOGO_PATH}")
            return None

        pixmap = pixmap.scaledToHeight(
            max_height,
            Qt.TransformationMode.SmoothTransformation,
        )

        logo_label = QLabel()
        logo_label.setPixmap(pixmap)
        logo_label.setFixedSize(pixmap.size())
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setContentsMargins(0, 0, 0, 0)
        logo_label.setStyleSheet("background: transparent;")
        logo_label.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )

        return logo_label

    except Exception as exc:
        print(f"Could not load logo: {exc}")
        return None


def build_header(window):
    """Build the Copperstone application header.

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

    # Three equal columns keep the logo centred across the complete header.
    layout = QGridLayout(header)
    layout.setContentsMargins(18, 8, 18, 8)
    layout.setHorizontalSpacing(0)
    layout.setVerticalSpacing(0)

    layout.setColumnStretch(0, 1)
    layout.setColumnStretch(1, 1)
    layout.setColumnStretch(2, 1)

    # Left column is intentionally empty.
    left_spacer = QWidget()
    left_spacer.setStyleSheet("background: transparent;")
    layout.addWidget(left_spacer, 0, 0)

    # Copperstone logo in the visual centre of the header.
    logo_widget = window._build_logo(max_height=80)

    if logo_widget is not None:
        layout.addWidget(
            logo_widget,
            0,
            1,
            Qt.AlignmentFlag.AlignCenter,
        )

    # Product name and version at the bottom-right.
    title = QLabel(f"{APP_NAME} v{APP_VERSION}")

    title_font = QFont(window.heading_font_family, 15)
    title_font.setBold(True)

    title.setFont(title_font)
    title.setStyleSheet(
        """
        color: white;
        background: transparent;
        """
    )
    title.setAlignment(
        Qt.AlignmentFlag.AlignRight
        | Qt.AlignmentFlag.AlignBottom
    )

    layout.addWidget(
        title,
        0,
        2,
        Qt.AlignmentFlag.AlignRight
        | Qt.AlignmentFlag.AlignBottom,
    )

    return header