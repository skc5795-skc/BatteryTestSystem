"""Shared Copperstone colours, fonts, and application-wide Qt styling."""

from PyQt6.QtGui import QFontDatabase

from core.config import COPPERSTONE_TEAL


COPPERSTONE_ORANGE = "#F4950D"
COPPERSTONE_DARK_GREY = "#141C2C"
COPPERSTONE_LIGHT_GREY = "#E7ECEC"


def resolve_font_family(*preferred_names: str) -> str:
    available = {name.lower(): name for name in QFontDatabase.families()}
    for preferred in preferred_names:
        match = available.get(preferred.lower())
        if match:
            return match
    return preferred_names[-1] if preferred_names else "Segoe UI"


def apply_application_style(window) -> None:
    """Apply the shared Copperstone stylesheet to the main window."""
    self = window
    self.setStyleSheet(
        f"""
        QMainWindow {{
            background: #FFFFFF;
        }}
        QWidget#centralWidget {{
            background: #FFFFFF;
        }}
        QWidget {{
            font-family: "{self.body_font_family}";
            color: {COPPERSTONE_DARK_GREY};
        }}
        QGroupBox {{
            border: 1px solid #CFD9D8;
            border-radius: 7px;
            margin-top: 10px;
            padding-top: 10px;
            background: #FFFFFF;
            color: {COPPERSTONE_TEAL};
            font-family: "{self.heading_font_family}";
            font-weight: 700;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 10px;
            top: 3px;
            padding: 0 5px;
            background: #FFFFFF;
        }}
        QLineEdit, QComboBox, QDoubleSpinBox {{
            min-height: 25px;
            border: 1px solid #B9C7C6;
            border-radius: 4px;
            padding: 2px 6px;
            background: #FFFFFF;
            selection-background-color: {COPPERSTONE_TEAL};
            selection-color: #FFFFFF;
        }}
        QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{
            border: 2px solid {COPPERSTONE_TEAL};
        }}
        QPushButton {{
            min-height: 27px;
            border: none;
            border-radius: 4px;
            padding: 3px 10px;
            font-weight: 700;
        }}
        QPushButton:disabled {{
            background: #D7DEDE;
            color: #8B9695;
        }}
        QToolTip {{
            background: #FFFFFF;
            color: {COPPERSTONE_DARK_GREY};
            border: 1px solid {COPPERSTONE_TEAL};
            padding: 4px;
        }}
        """
    )
