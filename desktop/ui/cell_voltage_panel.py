"""Individual cell-voltage display."""

from PyQt6.QtWidgets import QGridLayout, QGroupBox, QLabel

from core.config import CELL_COLORS, NUMBER_OF_CELLS


def build_cell_voltage_panel(window):
    self = window
    g = QGroupBox("Cell Voltages")
    grid = QGridLayout()
    self.cell_labels = []

    for i in range(NUMBER_OF_CELLS):
        row = i % 7
        col = (i // 7) * 2

        name = QLabel(f"C{i + 1}:")
        name.setStyleSheet(
            f"color:{CELL_COLORS[i % len(CELL_COLORS)]}; "
            "font-weight:bold;"
        )
        grid.addWidget(name, row, col)

        val = QLabel("-.---V")
        val.setStyleSheet(
            f"color:{CELL_COLORS[i % len(CELL_COLORS)]}; "
            "font-size:13px;"
        )
        grid.addWidget(val, row, col + 1)
        self.cell_labels.append(val)

    g.setLayout(grid)
    return g
