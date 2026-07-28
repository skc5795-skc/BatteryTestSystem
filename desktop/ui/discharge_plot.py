"""Live discharge graph and plot watermark."""

import os

import pyqtgraph as pg
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QGraphicsPixmapItem

from core.config import (
    BATTERY_CHEMISTRIES,
    CELL_COLORS,
    COPPERSTONE_TEAL,
    DEFAULT_CHEMISTRY,
)


def build_discharge_plot(window):
    self = window
    self.plot_widget = pg.PlotWidget()
    self.plot_widget.setBackground("w")
    self.plot_widget.setLabel("left", "Voltage", units="V")
    self.plot_widget.setLabel("bottom", "Time", units="s")
    self.plot_widget.setTitle(
        "Discharge Curves: Cell Voltages + Current",
        color="k",
        size="13pt",
    )
    self.plot_widget.addLegend(offset=(10, 10))
    self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
    self.plot_widget.setYRange(2.8, 4.3)

    self.current_axis = pg.ViewBox()
    self.plot_widget.scene().addItem(self.current_axis)
    self.plot_widget.getAxis("right").linkToView(self.current_axis)
    self.current_axis.setXLink(self.plot_widget)
    self.plot_widget.showAxis("right")
    self.plot_widget.getAxis("right").setLabel("Current", units="A")
    self.current_axis.setYRange(-60, 0)

    def update_views():
        self.current_axis.setGeometry(
            self.plot_widget.getViewBox().sceneBoundingRect()
        )
        self.current_axis.linkedViewChanged(
            self.plot_widget.getViewBox(), self.current_axis.XAxis
        )
        self._position_plot_watermark()

    self._create_plot_watermark()
    update_views()
    self.plot_widget.getViewBox().sigResized.connect(update_views)
    QTimer.singleShot(0, self._position_plot_watermark)

    chem = BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]
    discharge_end = chem.get("discharge_end_voltage", 3.0)
    self.storage_line = pg.InfiniteLine(
        pos=discharge_end,
        angle=0,
        pen=pg.mkPen(
            color="#e67e22",
            width=2,
            style=Qt.PenStyle.DashLine,
        ),
        label=f"Min {discharge_end}V",
        labelOpts={"color": "#e67e22", "position": 0.05},
    )
    self.plot_widget.addItem(self.storage_line)
    self.plot_lines = []

    self.current_line = pg.PlotDataItem(
        pen=pg.mkPen(
            color= "#FF00FF",
            width=4,
            style=Qt.PenStyle.SolidLine,
        ),
        name="Current (A)",
    )
    self.current_axis.addItem(self.current_line)
    return self.plot_widget


def create_plot_watermark(window) -> None:
    self = window
    """Load the faint Copperstone gear watermark for the plot area."""
    self.plot_watermark = None
    self.plot_watermark_pixmap = QPixmap()

    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    gear_path = os.path.join(project_root, "gear_watermark.png")

    # Fall back to gear.png so the app still works before the transparent
    # watermark file is copied into the project.
    if not os.path.exists(gear_path):
        gear_path = os.path.join(project_root, "gear.png")

    pixmap = QPixmap(gear_path)
    if pixmap.isNull():
        print(f"Could not load plot watermark: {gear_path}")
        return

    self.plot_watermark_pixmap = pixmap
    self.plot_watermark = QGraphicsPixmapItem(pixmap)
    self.plot_watermark.setTransformationMode(
        Qt.TransformationMode.SmoothTransformation
    )
    self.plot_watermark.setOpacity(0.090)
    self.plot_watermark.setZValue(-100)
    self.plot_watermark.setAcceptedMouseButtons(
        Qt.MouseButton.NoButton
    )
    self.plot_widget.scene().addItem(self.plot_watermark)


def position_plot_watermark(window) -> None:
    self = window
    """Keep the watermark centred inside the visible plot rectangle."""
    if not getattr(self, "plot_watermark", None):
        return
    if self.plot_watermark_pixmap.isNull():
        return

    plot_rect = self.plot_widget.getViewBox().sceneBoundingRect()
    if plot_rect.width() <= 1 or plot_rect.height() <= 1:
        return

    # Use roughly half the plot height so the gear is visible but does not
    # compete with the voltage and current traces.
    target_size = min(plot_rect.width(), plot_rect.height()) * 1
    source_size = max(
        self.plot_watermark_pixmap.width(),
        self.plot_watermark_pixmap.height(),
    )
    if source_size <= 0:
        return

    scale = target_size / source_size
    self.plot_watermark.setScale(scale)

    displayed_width = self.plot_watermark_pixmap.width() * scale
    displayed_height = self.plot_watermark_pixmap.height() * scale
    centre = plot_rect.center()

    self.plot_watermark.setPos(
        centre.x() - displayed_width / 2.0,
        centre.y() - displayed_height / 2.0,
    )


def initialize_plot_lines(window, cell_count: int) -> None:
    self = window
    for line in self.plot_lines:
        self.plot_widget.removeItem(line)
    self.plot_lines = []

    for i in range(cell_count):
        pen = pg.mkPen(
            color=CELL_COLORS[i % len(CELL_COLORS)], width=2
        )
        line = self.plot_widget.plot(
            [],
            [],
            pen=pen,
            name=f"Cell {i + 1}",
        )
        self.plot_lines.append(line)
