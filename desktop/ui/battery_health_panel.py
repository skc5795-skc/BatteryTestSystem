"""Battery health summary and capacity progress section."""

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QGroupBox, QHBoxLayout, QLabel

from desktop.ui.capacity_bar import CapacityProgressBar


def build_battery_health_panel(window):
    self = window
    g = QGroupBox("Battery Health")
    h = QHBoxLayout()
    h.setSpacing(10)

    h.addWidget(QLabel("Overall:"))
    self.health_overall = QLabel("-- Waiting --")
    self.health_overall.setStyleSheet(
        "font-weight:bold; font-size:14px; color:gray;"
    )
    h.addWidget(self.health_overall)

    h.addSpacing(20)
    h.addWidget(QLabel("Imbalance:"))
    self.health_imbalance = QLabel("--")
    self.health_imbalance.setStyleSheet(
        "font-size:13px; color:gray;"
    )
    h.addWidget(self.health_imbalance)

    h.addSpacing(20)
    h.addWidget(QLabel("Critical Cells:"))
    self.health_critical = QLabel("--")
    self.health_critical.setStyleSheet(
        "font-size:13px; color:gray;"
    )
    h.addWidget(self.health_critical)

    h.addStretch()
    h.addWidget(QLabel("Capacity Progress:"))
    self.capacity_progress = CapacityProgressBar()
    self.capacity_progress.setMinimumWidth(300)
    self.capacity_progress.setMaximumWidth(430)
    self.capacity_progress.setFont(QFont(self.body_font_family, 9))
    self.capacity_progress.set_capacity(
        0.0, self.capacity_spin.value()
    )
    h.addWidget(self.capacity_progress, stretch=1)

    g.setLayout(h)
    return g
