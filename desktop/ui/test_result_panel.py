"""Test result, override, and export controls."""

from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from core.config import COPPERSTONE_TEAL
from desktop.ui.battery_theme import COPPERSTONE_ORANGE


def build_test_result_panel(window):
    """Build the result and report-export portion of the bottom panel."""
    self = window

    result_grid = QGridLayout()
    result_grid.setVerticalSpacing(6)

    result_grid.addWidget(QLabel("Test Result:"), 0, 0)
    self.result_label = QLabel("--")
    self.result_label.setStyleSheet(
        "font-size:22px; font-weight:bold; color:gray;"
    )
    result_grid.addWidget(self.result_label, 0, 1)

    self.stop_reason_label = QLabel("")
    self.stop_reason_label.setWordWrap(True)
    self.stop_reason_label.setMinimumWidth(245)
    self.stop_reason_label.setStyleSheet(
        "font-size:11px; color:#5A6665; font-weight:600;"
    )
    result_grid.addWidget(self.stop_reason_label, 1, 0, 1, 2)

    result_grid.addWidget(QLabel("Override:"), 2, 0)
    self.override_combo = QComboBox()
    self.override_combo.addItems(
        ["No override", "Mark as PASS", "Mark as FAIL"]
    )
    self.override_combo.currentIndexChanged.connect(self._on_override)
    result_grid.addWidget(self.override_combo, 2, 1)

    self.override_reason_edit = QLineEdit()
    self.override_reason_edit.setPlaceholderText(
        "Override reason (optional)"
    )
    result_grid.addWidget(self.override_reason_edit, 3, 0, 1, 2)

    export_layout = QHBoxLayout()
    export_layout.setSpacing(8)

    self.export_csv_btn = QPushButton("Export CSV")
    self.export_csv_btn.setEnabled(False)
    self.export_csv_btn.setStyleSheet(
        f"background:{COPPERSTONE_TEAL}; color:white; font-weight:bold;"
    )
    self.export_csv_btn.clicked.connect(self._export_csv)

    self.export_pdf_btn = QPushButton("Export PDF")
    self.export_pdf_btn.setEnabled(False)
    self.export_pdf_btn.setStyleSheet(
        f"background:{COPPERSTONE_ORANGE}; color:white; font-weight:bold;"
    )
    self.export_pdf_btn.clicked.connect(self._export_pdf)

    export_layout.addWidget(self.export_csv_btn)
    export_layout.addWidget(self.export_pdf_btn)
    result_grid.addLayout(export_layout, 4, 0, 1, 2)

    panel = QWidget()
    panel.setLayout(result_grid)
    return panel
