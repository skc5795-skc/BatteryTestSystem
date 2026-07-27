"""Pre-test validation controls."""

from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from core.config import COPPERSTONE_GREEN
from desktop.ui.battery_theme import COPPERSTONE_ORANGE


def build_pre_test_panel(window):
    self = window
    g = QGroupBox("Pre-Test Check")
    h = QHBoxLayout()

    self.check_cells_label = self._make_status_label("Waiting...")
    self.check_charged_label = self._make_status_label("Waiting...")
    self.check_balanced_label = self._make_status_label("Waiting...")

    h.addWidget(QLabel("Cells Detected:"))
    h.addWidget(self.check_cells_label)
    h.addSpacing(20)
    h.addWidget(QLabel("Cells Charged (live):"))
    h.addWidget(self.check_charged_label)
    h.addSpacing(20)
    h.addWidget(QLabel("Cells Balanced (live):"))
    h.addWidget(self.check_balanced_label)
    h.addStretch()

    self.start_btn = QPushButton("▶ START")
    self.start_btn.setEnabled(False)
    self.start_btn.setMinimumWidth(115)
    self.start_btn.setMaximumWidth(135)
    self.start_btn.clicked.connect(self._toggle_test)
    self._set_start_stop_mode(testing=False, enabled=False)
    h.addWidget(self.start_btn)

    self.clear_btn = QPushButton("Reset")
    self.clear_btn.setEnabled(False)
    self.clear_btn.setMinimumWidth(95)
    self.clear_btn.setMaximumWidth(110)
    self.clear_btn.setStyleSheet(
        f"background:{COPPERSTONE_ORANGE}; color:white; font-weight:bold;"
    )
    self.clear_btn.clicked.connect(self._clear_all)
    h.addWidget(self.clear_btn)

    g.setLayout(h)
    return g
