"""Live battery statistics panel."""

from PyQt6.QtWidgets import QGridLayout, QLabel, QWidget

from core.config import COPPERSTONE_TEAL


def build_live_info_panel(window):
    """Build the live-statistics portion of the combined bottom panel."""
    self = window

    stats_grid = QGridLayout()
    stats_grid.setHorizontalSpacing(9)
    stats_grid.setVerticalSpacing(6)
    self.stat_labels = {}

    rows = [
        ("Total Voltage", "Avg Voltage", "Min Voltage", "Max Voltage"),
        ("Spread", "Current", "Runtime", "Measured Capacity"),
        ("Capacity %", "SoC (BMS)", "BMS Capacity", "Final Cell Std Dev"),
    ]

    for row_idx, row_items in enumerate(rows):
        for col_idx, name in enumerate(row_items):
            if not name:
                continue

            label = QLabel(f"{name}:")
            label.setStyleSheet("font-weight:bold;")
            stats_grid.addWidget(label, row_idx, col_idx * 2)

            value = QLabel("--")
            value.setStyleSheet(
                f"color:{COPPERSTONE_TEAL}; "
                "font-size:13px; font-weight:bold;"
            )
            stats_grid.addWidget(value, row_idx, col_idx * 2 + 1)
            self.stat_labels[name] = value

    panel = QWidget()
    panel.setLayout(stats_grid)
    return panel
