"""
Battery Test System - Desktop UI (PyQt6)
Production battery discharge test interface.
"""

import time
import serial.tools.list_ports
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QGroupBox, QGridLayout, QLineEdit,
    QMessageBox, QFileDialog, QDoubleSpinBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap
import pyqtgraph as pg

from core.config import (
    BATTERY_CHEMISTRIES, DEFAULT_CHEMISTRY, DEFAULT_RATED_CAPACITY_AH,
    DEFAULT_PASS_THRESHOLD_PCT, NUMBER_OF_CELLS, CELL_COLORS,
    AVAILABLE_BAUD_RATES, DEFAULT_BAUD_RATE, SERIAL_NUMBER_PREFIX,
    APP_NAME, APP_VERSION, WINDOW_WIDTH, WINDOW_HEIGHT,
    CELL_IMBALANCE_WARNING_V, LOGO_PATH
)
from core.battery_test import BatteryTestEngine, TestStatus, TestResult
from core.report_generator import (generate_csv, get_csv_filename,
                                    generate_pdf, get_pdf_filename)
from desktop.serial_thread import SerialReadThread


class BatteryTestUI(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT)

        # ── State ─────────────────────────────────────────────────────────────
        self.engine           = BatteryTestEngine()
        self.serial_thread    = None
        self.is_connected     = False
        self.is_testing       = False        # Single flag, not relying on session status
        self.pre_check_passed = False
        self.latest_voltages  = []
        self.latest_current   = 0.0

        self.setup_ui()

    # ─────────────────────────────────────────────────────────────────────────
    # UI CONSTRUCTION
    # ─────────────────────────────────────────────────────────────────────────

    def _build_logo(self):
        """Load and display company logo if available"""
        import os
        if not os.path.exists(LOGO_PATH):
            return None

        try:
            logo_label = QLabel()
            pixmap = QPixmap(LOGO_PATH)
            # Scale to reasonable size if needed (max height 60px)
            if pixmap.height() > 60:
                pixmap = pixmap.scaledToHeight(60, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(pixmap)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_label.setStyleSheet("margin: 5px;")
            return logo_label
        except Exception as e:
            print(f"⚠ Could not load logo: {e}")
            return None

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(6)

        # Add logo if available
        logo_widget = self._build_logo()
        if logo_widget:
            root.addWidget(logo_widget)

        root.addWidget(self._build_top_bar())
        root.addWidget(self._build_pre_check_panel())

        mid = QHBoxLayout()
        mid.addWidget(self._build_plot(), stretch=3)
        mid.addWidget(self._build_cell_panel(), stretch=1)
        root.addLayout(mid)

        root.addWidget(self._build_health_panel())
        root.addWidget(self._build_stats_panel())

    # ── Top Bar ───────────────────────────────────────────────────────────────

    def _build_top_bar(self):
        g = QGroupBox("Test Setup")
        h = QHBoxLayout()

        h.addWidget(QLabel("Battery Serial:"))
        self.serial_edit = QLineEdit(SERIAL_NUMBER_PREFIX)
        self.serial_edit.setMaximumWidth(150)
        self.serial_edit.setFont(QFont('Courier', 11))
        self.serial_edit.setPlaceholderText(f"{SERIAL_NUMBER_PREFIX}001")
        h.addWidget(self.serial_edit)

        h.addWidget(QLabel("Chemistry:"))
        self.chemistry_combo = QComboBox()
        for key, val in BATTERY_CHEMISTRIES.items():
            self.chemistry_combo.addItem(val['name'], key)
        self.chemistry_combo.setCurrentText(
            BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]['name'])
        self.chemistry_combo.currentIndexChanged.connect(self._on_chemistry_changed)
        h.addWidget(self.chemistry_combo)

        h.addWidget(QLabel("Storage V:"))
        self.storage_label = QLabel(
            f"{BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]['storage_voltage']:.2f} V")
        self.storage_label.setStyleSheet("font-weight:bold; color:#e67e22;")
        h.addWidget(self.storage_label)

        h.addWidget(QLabel("Rated Capacity (Ah):"))
        self.capacity_spin = QDoubleSpinBox()
        self.capacity_spin.setRange(1.0, 1000.0)
        self.capacity_spin.setSingleStep(1.0)
        self.capacity_spin.setDecimals(1)
        self.capacity_spin.setValue(DEFAULT_RATED_CAPACITY_AH)
        h.addWidget(self.capacity_spin)

        h.addWidget(QLabel("Pass >= :"))
        self.threshold_combo = QComboBox()
        for pct in [80, 85, 90, 95, 100]:
            self.threshold_combo.addItem(f"{pct}%", pct)
        self.threshold_combo.setCurrentText(f"{DEFAULT_PASS_THRESHOLD_PCT}%")
        h.addWidget(self.threshold_combo)

        h.addSpacing(10)

        h.addWidget(QLabel("COM Port:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(180)
        self._refresh_ports()
        h.addWidget(self.port_combo)

        refresh_btn = QPushButton("↻")
        refresh_btn.setMaximumWidth(28)
        refresh_btn.clicked.connect(self._refresh_ports)
        h.addWidget(refresh_btn)

        h.addWidget(QLabel("Baud:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(AVAILABLE_BAUD_RATES)
        self.baud_combo.setCurrentText(DEFAULT_BAUD_RATE)
        h.addWidget(self.baud_combo)

        self.connect_btn = QPushButton("Connect BMS")
        self.connect_btn.setStyleSheet(
            "background:#2980b9; color:white; font-weight:bold;")
        self.connect_btn.clicked.connect(self._toggle_connection)
        h.addWidget(self.connect_btn)

        h.addStretch()

        self.status_label = QLabel("Not connected")
        self.status_label.setStyleSheet("color:#666; font-weight:bold;")
        h.addWidget(self.status_label)

        g.setLayout(h)
        return g

    # ── Pre-Check Panel ───────────────────────────────────────────────────────

    def _build_pre_check_panel(self):
        g = QGroupBox("Pre-Test Check")
        h = QHBoxLayout()

        self.check_cells_label    = self._make_status_label("Waiting...")
        self.check_charged_label  = self._make_status_label("Waiting...")
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

        self.start_btn = QPushButton("▶  START TEST")
        self.start_btn.setEnabled(False)
        self.start_btn.setMinimumWidth(160)
        self.start_btn.setStyleSheet(
            "background:#27ae60; color:white; font-size:14px; font-weight:bold;")
        self.start_btn.clicked.connect(self._start_test)
        h.addWidget(self.start_btn)

        self.stop_btn = QPushButton("■  STOP TEST")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMinimumWidth(160)
        self.stop_btn.setStyleSheet(
            "background:#e74c3c; color:white; font-size:14px; font-weight:bold;")
        self.stop_btn.clicked.connect(self._stop_test)
        h.addWidget(self.stop_btn)

        g.setLayout(h)
        return g

    # ── Plot ──────────────────────────────────────────────────────────────────

    def _build_plot(self):
        """Create single plot with dual Y-axes: voltage (left) and current (right)"""
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', 'Voltage', units='V')
        self.plot_widget.setLabel('bottom', 'Time', units='s')
        self.plot_widget.setTitle('Discharge Curves: Cell Voltages + Current', color='k', size='13pt')
        self.plot_widget.addLegend(offset=(10, 10))
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)

        # Voltage Y-axis range (will auto-adjust, but set reasonable defaults)
        self.plot_widget.setYRange(2.8, 4.3)

        # Add second Y-axis for current (right side)
        self.current_axis = pg.ViewBox()
        self.plot_widget.scene().addItem(self.current_axis)
        self.plot_widget.getAxis('right').linkToView(self.current_axis)
        self.current_axis.setXLink(self.plot_widget)
        self.plot_widget.showAxis('right')
        self.plot_widget.getAxis('right').setLabel('Current', units='A')

        # Scale current axis: 60A discharge maps to voltage range (2.8-4.3V = 1.5V range)
        # We'll set current range as 0 to -60A (negative = discharging)
        self.current_axis.setYRange(-60, 0)

        # Update views when plot is resized
        def update_views():
            self.current_axis.setGeometry(self.plot_widget.getViewBox().sceneBoundingRect())
            self.current_axis.linkedViewChanged(self.plot_widget.getViewBox(), self.current_axis.XAxis)

        update_views()
        self.plot_widget.getViewBox().sigResized.connect(update_views)

        # Voltage plot lines (left Y-axis)
        chem = BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]
        discharge_end = chem.get('discharge_end_voltage', 3.00)
        self.storage_line = pg.InfiniteLine(
            pos=discharge_end, angle=0,
            pen=pg.mkPen(color='#e67e22', width=2,
                         style=Qt.PenStyle.DashLine),
            label=f"Min {discharge_end}V",
            labelOpts={'color': '#e67e22', 'position': 0.05}
        )
        self.plot_widget.addItem(self.storage_line)
        self.plot_lines = []

        # Current plot line (right Y-axis) - thicker and different color
        self.current_line = pg.PlotDataItem(
            pen=pg.mkPen(color='#2c3e50', width=3, style=Qt.PenStyle.SolidLine),
            name='Current (A)'
        )
        self.current_axis.addItem(self.current_line)

        return self.plot_widget

    def _init_plot_lines(self, cell_count: int):
        for line in self.plot_lines:
            self.plot_widget.removeItem(line)
        self.plot_lines = []
        for i in range(cell_count):
            pen  = pg.mkPen(color=CELL_COLORS[i % len(CELL_COLORS)], width=2)
            line = self.plot_widget.plot([], [], pen=pen, name=f'Cell {i+1}')
            self.plot_lines.append(line)
        print(f"   ✓ Plot lines created: {cell_count} cells")

    # ── Cell Panel ────────────────────────────────────────────────────────────

    def _build_cell_panel(self):
        g = QGroupBox("Cell Voltages")
        grid = QGridLayout()
        self.cell_labels = []
        for i in range(NUMBER_OF_CELLS):
            row = i % 7
            col = (i // 7) * 2
            name = QLabel(f"C{i+1}:")
            name.setStyleSheet(
                f"color:{CELL_COLORS[i % len(CELL_COLORS)]}; font-weight:bold;")
            grid.addWidget(name, row, col)
            val = QLabel("-.---V")
            val.setStyleSheet(
                f"color:{CELL_COLORS[i % len(CELL_COLORS)]}; font-size:13px;")
            grid.addWidget(val, row, col + 1)
            self.cell_labels.append(val)
        g.setLayout(grid)
        return g

    # ── Health Panel ──────────────────────────────────────────────────────────

    def _build_health_panel(self):
        g = QGroupBox("Battery Health")
        h = QHBoxLayout()

        h.addWidget(QLabel("Overall:"))
        self.health_overall = QLabel("-- Waiting --")
        self.health_overall.setStyleSheet(
            "font-weight:bold; font-size:14px; color:gray;")
        h.addWidget(self.health_overall)

        h.addSpacing(30)
        h.addWidget(QLabel("Imbalance:"))
        self.health_imbalance = QLabel("--")
        self.health_imbalance.setStyleSheet("font-size:13px; color:gray;")
        h.addWidget(self.health_imbalance)

        h.addSpacing(30)
        h.addWidget(QLabel("Critical Cells:"))
        self.health_critical = QLabel("--")
        self.health_critical.setStyleSheet("font-size:13px; color:gray;")
        h.addWidget(self.health_critical)

        h.addSpacing(30)
        h.addWidget(QLabel("Discharge Target:"))
        self.health_target = QLabel("--")
        self.health_target.setStyleSheet("font-size:13px; color:gray;")
        h.addWidget(self.health_target)

        h.addStretch()
        g.setLayout(h)
        return g

    # ── Stats + Result Panel ──────────────────────────────────────────────────

    def _build_stats_panel(self):
        g = QGroupBox("Live Statistics  |  Test Result")
        h = QHBoxLayout()

        stats_grid = QGridLayout()
        self.stat_labels = {}
        rows = [
            ('Avg Voltage', 'Min Voltage', 'Max Voltage', 'Spread'),
            ('Current',     'Runtime',     'Measured Capacity', 'Capacity %'),
            ('SoC (BMS)',   'BMS Capacity', '', ''),
        ]
        for row_idx, row_items in enumerate(rows):
            for col_idx, name in enumerate(row_items):
                if not name:  # Skip empty labels
                    continue
                lbl = QLabel(f"{name}:")
                lbl.setStyleSheet("font-weight:bold;")
                stats_grid.addWidget(lbl, row_idx, col_idx * 2)
                val = QLabel("--")
                val.setStyleSheet("color:#2980b9; font-size:13px;")
                stats_grid.addWidget(val, row_idx, col_idx * 2 + 1)
                self.stat_labels[name] = val

        stats_w = QWidget()
        stats_w.setLayout(stats_grid)
        h.addWidget(stats_w, stretch=2)

        result_grid = QGridLayout()

        result_grid.addWidget(QLabel("Measured Capacity:"), 0, 0)
        self.cap_ah_label = QLabel("0.0000 Ah")
        self.cap_ah_label.setStyleSheet(
            "font-size:15px; font-weight:bold; color:#1a1a2e;")
        result_grid.addWidget(self.cap_ah_label, 0, 1)

        result_grid.addWidget(QLabel("Capacity %:"), 1, 0)
        self.cap_pct_label = QLabel("0.0 %")
        self.cap_pct_label.setStyleSheet(
            "font-size:15px; font-weight:bold; color:#1a1a2e;")
        result_grid.addWidget(self.cap_pct_label, 1, 1)

        result_grid.addWidget(QLabel("Test Result:"), 2, 0)
        self.result_label = QLabel("--")
        self.result_label.setStyleSheet(
            "font-size:18px; font-weight:bold; color:gray;")
        result_grid.addWidget(self.result_label, 2, 1)

        result_grid.addWidget(QLabel("Override:"), 3, 0)
        self.override_combo = QComboBox()
        self.override_combo.addItems(['No override', 'Mark as PASS', 'Mark as FAIL'])
        self.override_combo.currentIndexChanged.connect(self._on_override)
        result_grid.addWidget(self.override_combo, 3, 1)

        self.override_reason_edit = QLineEdit()
        self.override_reason_edit.setPlaceholderText(
            "Override reason (optional)")
        result_grid.addWidget(self.override_reason_edit, 4, 0, 1, 2)

        export_h = QHBoxLayout()
        self.export_csv_btn = QPushButton("Export CSV")
        self.export_csv_btn.setEnabled(False)
        self.export_csv_btn.clicked.connect(self._export_csv)
        self.export_pdf_btn = QPushButton("Export PDF")
        self.export_pdf_btn.setEnabled(False)
        self.export_pdf_btn.clicked.connect(self._export_pdf)
        export_h.addWidget(self.export_csv_btn)
        export_h.addWidget(self.export_pdf_btn)
        result_grid.addLayout(export_h, 5, 0, 1, 2)

        result_w = QWidget()
        result_w.setLayout(result_grid)
        h.addWidget(result_w, stretch=1)

        g.setLayout(h)
        return g

    # ─────────────────────────────────────────────────────────────────────────
    # CONNECTION
    # ─────────────────────────────────────────────────────────────────────────

    def _refresh_ports(self):
        self.port_combo.clear()
        for p in serial.tools.list_ports.comports():
            self.port_combo.addItem(f"{p.device} - {p.description}")

    def _toggle_connection(self):
        if self.is_connected:
            self._disconnect_bms()
        else:
            self._connect_bms()

    def _connect_bms(self):
        port_text = self.port_combo.currentText()
        if not port_text:
            self._set_status("No port selected", "#e74c3c")
            return
        port = port_text.split(' - ')[0]
        baud = int(self.baud_combo.currentText())

        self.serial_thread = SerialReadThread(port, baud)
        self.serial_thread.voltage_received.connect(self._on_voltage)
        self.serial_thread.info_received.connect(self._on_info)
        self.serial_thread.error_occurred.connect(self._on_error)
        self.serial_thread.status_update.connect(self._on_status_msg)
        self.serial_thread.start()

        self.is_connected = True
        self.connect_btn.setText("Disconnect BMS")
        self.connect_btn.setStyleSheet(
            "background:#7f8c8d; color:white; font-weight:bold;")
        self._set_status(f"Connected: {port}", "#27ae60")

    def _disconnect_bms(self):
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None

        self.is_connected     = False
        self.is_testing       = False
        self.pre_check_passed = False

        self.connect_btn.setText("Connect BMS")
        self.connect_btn.setStyleSheet(
            "background:#2980b9; color:white; font-weight:bold;")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self._set_status("Disconnected", "#666")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST CONTROL
    # ─────────────────────────────────────────────────────────────────────────

    def _start_test(self):
        print("\n========== START TEST CLICKED ==========")

        # ── Validate serial number ────────────────────────────────────────────
        serial_no = self.serial_edit.text().strip()
        print(f"Serial entered: '{serial_no}'")

        if not serial_no or serial_no == SERIAL_NUMBER_PREFIX:
            print("BLOCKED: Invalid serial number")
            QMessageBox.warning(
                self,
                "Serial Number Required",
                f"Please enter a complete battery serial number.\n\n"
                f"Example: {SERIAL_NUMBER_PREFIX}001\n\n"
                f"The serial number cannot be just '{SERIAL_NUMBER_PREFIX}'."
            )
            self.serial_edit.setFocus()
            self.serial_edit.setStyleSheet(
                "border: 2px solid red; background: #fff0f0;")
            return

        self.serial_edit.setStyleSheet("")

        # ── Collect settings ──────────────────────────────────────────────────
        chemistry = self.chemistry_combo.currentData()
        rated_ah  = self.capacity_spin.value()
        threshold = self.threshold_combo.currentData()

        print(f"Chemistry : {chemistry}")
        print(f"Rated Ah  : {rated_ah}")
        print(f"Threshold : {threshold}%")
        print(f"Voltages  : {len(self.latest_voltages)} cells ready")

        # ── Create session and start ──────────────────────────────────────────
        self.engine.new_session(serial_no, chemistry, rated_ah, threshold)
        self.engine.start_test()

        print(f"Session status: {self.engine.session.status}")

        # ── Initialize plot lines ─────────────────────────────────────────────
        cell_count = len(self.latest_voltages) if self.latest_voltages else NUMBER_OF_CELLS
        self._init_plot_lines(cell_count)

        # ── Flip testing flag AFTER session is fully set up ───────────────────
        self.is_testing = True

        # ── Update buttons ────────────────────────────────────────────────────
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.export_csv_btn.setEnabled(False)
        self.export_pdf_btn.setEnabled(False)
        self.override_combo.setCurrentIndex(0)

        self._set_status(f"▶ Testing: {serial_no}", "#27ae60")
        print(f"✓ Test running — is_testing={self.is_testing}")
        print("=========================================\n")

    def _stop_test(self):
        print("\n========== STOP TEST ==========")
        self.is_testing = False
        self.engine.stop_test()

        self.start_btn.setEnabled(self.pre_check_passed and self.is_connected)
        self.stop_btn.setEnabled(False)
        self.export_csv_btn.setEnabled(True)
        self.export_pdf_btn.setEnabled(True)

        self._refresh_result_display()
        result = self.engine.session.result.value if self.engine.session else "?"
        self._set_status(f"■ Stopped — Result: {result}", "#e74c3c")
        print(f"Result: {result}")
        print("================================\n")

    # ─────────────────────────────────────────────────────────────────────────
    # DATA HANDLERS
    # ─────────────────────────────────────────────────────────────────────────

    def _on_voltage(self, voltages: list, timestamp: float):
        """Called every second with new cell voltages from BMS."""
        self.latest_voltages = voltages

        if self.is_testing:
            # ── TESTING: record + update graph ───────────────────────────────
            session = self.engine.session
            if session and session.status == TestStatus.TESTING:

                # Record sample
                self.engine.record_voltage_sample(voltages, self.latest_current)
                n = len(session.samples)

                # Log every 5 samples
                if n <= 3 or n % 5 == 0:
                    live = [v for v in voltages if v >= 2.0]
                    avg  = sum(live) / len(live) if live else 0
                    print(f"Sample #{n} | t={timestamp:.0f}s | "
                          f"avg={avg:.3f}V | "
                          f"cap={session.calculated_capacity_ah:.4f}Ah")

                # Init plot lines if somehow missing
                if not self.plot_lines:
                    self._init_plot_lines(len(voltages))

                # Update voltage graph
                t = session.time_data
                for i, line in enumerate(self.plot_lines):
                    if i < len(session.cell_data) and session.cell_data[i]:
                        line.setData(t, session.cell_data[i])

                # Update current graph
                current_data = [s.current_ma / 1000.0 for s in session.samples]  # Convert mA to A
                self.current_line.setData(t, current_data)

                # Update capacity display in both places
                ah  = session.calculated_capacity_ah
                pct = session.capacity_percent
                self.cap_ah_label.setText(
                    f"{ah:.4f} Ah  ({ah*1000:.1f} mAh)")
                self.cap_pct_label.setText(f"{pct:.1f} %")
                self.stat_labels['Runtime'].setText(session.runtime_str)
                self.stat_labels['Measured Capacity'].setText(f"{ah:.4f} Ah")
                self.stat_labels['Capacity %'].setText(f"{pct:.1f}%")

                # Note: BMS will trigger cell_uv_p when minimum voltage reached
                # Auto-stop is handled in _on_info based on protection_status

        else:
            # ── NOT TESTING: run pre-check on incoming data ───────────────────
            self._run_pre_check(voltages)

        # Always update labels and health
        self._update_cell_labels(voltages)
        self._update_health_panel(voltages)
        self._update_live_stats(voltages)

    def _on_info(self, info: dict):
        """Called every 2 seconds with BMS basic info."""
        current = info.get('current_ma', 0)
        self.latest_current = current

        # Update current display immediately (don't wait for next voltage sample)
        if current < 0:
            self.stat_labels['Current'].setText(f"{current/1000.0:.2f} A  (Discharging)")
        elif current > 0:
            self.stat_labels['Current'].setText(f"+{current/1000.0:.2f} A  (Charging)")
        else:
            self.stat_labels['Current'].setText("0.00 A  (Idle)")

        # Update SoC and BMS Capacity
        soc = info.get('rsoc_percent', 0)
        bms_cap = info.get('residual_capacity_mah', 0)
        self.stat_labels['SoC (BMS)'].setText(f"{soc}%")
        self.stat_labels['BMS Capacity'].setText(f"{bms_cap} mAh")

        print(f"⚡ Current: {current/1000.0:.2f} A | SoC: {soc}% | BMS Cap: {bms_cap} mAh")

        if self.engine.session:
            self.engine.update_bms_info(info)

            # Check BMS protection status for cell undervoltage (bit 0)
            if self.is_testing:
                protection_status = info.get('protection_status', 0)
                cell_uv_p = (protection_status & 0x01) != 0  # Bit 0 = cell undervoltage protection

                if cell_uv_p:
                    print(f"⚠ BMS PROTECTION TRIGGERED: Cell undervoltage protection active!")
                    print(f"   Protection status: 0x{protection_status:04X}")
                    self.engine.stop_test()
                    self.is_testing = False
                    self.stop_btn.setEnabled(False)
                    self.start_btn.setEnabled(False)
                    self.export_csv_btn.setEnabled(True)
                    self.export_pdf_btn.setEnabled(True)
                    self._refresh_result_display()
                    self._set_status(
                        "🛑 BMS Protection: Cell undervoltage detected!",
                        "#e74c3c")

    def _on_error(self, msg: str):
        print(f"✗ Error: {msg}")
        self._set_status(f"Error: {msg}", "#e74c3c")
        if self.is_testing:
            self.engine.abort_test()
            self.is_testing = False
            self.stop_btn.setEnabled(False)
            self.start_btn.setEnabled(False)

    def _on_status_msg(self, msg: str):
        print(f"BMS: {msg}")

    # ─────────────────────────────────────────────────────────────────────────
    # PRE-CHECK  (runs only when not testing)
    # ─────────────────────────────────────────────────────────────────────────

    def _run_pre_check(self, voltages: list):
        """
        Run pre-check on live voltages.
        Uses a TEMPORARY engine so it never touches self.engine.session.
        """
        temp = BatteryTestEngine()
        temp.new_session(
            serial_number      = SERIAL_NUMBER_PREFIX,
            chemistry          = self.chemistry_combo.currentData() or DEFAULT_CHEMISTRY,
            rated_capacity_ah  = self.capacity_spin.value(),
            pass_threshold_pct = self.threshold_combo.currentData() or DEFAULT_PASS_THRESHOLD_PCT
        )
        result     = temp.run_pre_check(voltages)
        dead_count = sum(1 for v in voltages if v < 2.0)

        # Cells detected label
        if result.all_cells_found and dead_count == 0:
            self._set_check(self.check_cells_label, True,
                            f"{result.cell_count}/{NUMBER_OF_CELLS} cells ✅")
        elif result.all_cells_found and dead_count > 0:
            self.check_cells_label.setText(
                f"{result.cell_count}/{NUMBER_OF_CELLS} ({dead_count} dead ⚠)")
            self.check_cells_label.setStyleSheet(
                "color:#f39c12; font-size:13px; font-weight:bold;")
        else:
            self._set_check(self.check_cells_label, False,
                            f"{len(voltages)}/{NUMBER_OF_CELLS} cells ✗")

        # Charged label (live only) - show threshold so user knows what's needed
        chem_key  = self.chemistry_combo.currentData() or DEFAULT_CHEMISTRY
        chem_cfg  = BATTERY_CHEMISTRIES.get(chem_key, BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY])
        min_start = chem_cfg.get('min_start_voltage', 3.50)

        if result.cells_charged:
            self._set_check(
                self.check_charged_label, True,
                f"Min: {result.min_voltage:.3f}V ✅ (need ≥ {min_start:.2f}V)"
            )
        else:
            self._set_check(
                self.check_charged_label, False,
                f"Min: {result.min_voltage:.3f}V ✗ — need ≥ {min_start:.2f}V. "
                f"Please charge battery first!"
            )

        # Balanced label (live only)
        if result.cells_balanced:
            self._set_check(
                self.check_balanced_label, True,
                f"Spread: {result.spread:.3f}V ✅"
            )
        else:
            self._set_check(
                self.check_balanced_label, False,
                f"Spread: {result.spread:.3f}V ✗ — need < {CELL_IMBALANCE_WARNING_V:.2f}V"
            )

        # Enable START only if pre-check passes and connected and not already testing
        self.pre_check_passed = result.passed
        self.start_btn.setEnabled(
            result.passed and self.is_connected and not self.is_testing)

        # ── Show helpful message if pre-check fails ───────────────────────────
        if not result.passed and self.is_connected:
            # Build a user-friendly explanation
            chem_name = self.chemistry_combo.currentText()
            temp = BatteryTestEngine()
            temp.new_session('', self.chemistry_combo.currentData() or DEFAULT_CHEMISTRY,
                           self.capacity_spin.value(), DEFAULT_PASS_THRESHOLD_PCT)
            chem_config = temp.session.chemistry_config
            min_start_v = chem_config.get('min_start_voltage', MIN_START_VOLTAGE)

            issues = []
            if not result.all_cells_found:
                issues.append(f"• Expected {NUMBER_OF_CELLS} cells, found {len(voltages)}")
            if not result.cells_charged:
                issues.append(
                    f"• Cells below start voltage for {chem_name} "
                    f"(min: {result.min_voltage:.3f}V < {min_start_v:.2f}V required)\n"
                    f"  → Charge battery, OR select correct chemistry if already at storage voltage"
                )
            if not result.cells_balanced:
                issues.append(f"• Cell imbalance too high (spread: {result.spread:.3f}V > 0.05V)")

            if issues:
                reason = "\n".join(issues)
                self._set_status(
                    f"⚠ Pre-check failed — START disabled:\n{reason}",
                    "#e67e22"
                )

    # ─────────────────────────────────────────────────────────────────────────
    # UI UPDATE HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _update_cell_labels(self, voltages: list):
        chem_key = DEFAULT_CHEMISTRY
        if self.engine.session:
            fail_v = self.engine.session.chemistry_config.get('cell_fail_voltage', 3.0)
        else:
            chem_key = self.chemistry_combo.currentData() or DEFAULT_CHEMISTRY
            fail_v   = BATTERY_CHEMISTRIES[chem_key]['cell_fail_voltage']

        for i, (v, lbl) in enumerate(zip(voltages, self.cell_labels)):
            color = CELL_COLORS[i % len(CELL_COLORS)]
            if v < 1.0:
                lbl.setStyleSheet(
                    "color:red; font-weight:bold; "
                    "background-color:#FFE0E0; border-radius:3px;")
                lbl.setText(f"{v:.3f}V ⚠DEAD")
            elif v < 2.0:
                lbl.setStyleSheet("color:#c0392b; font-weight:bold;")
                lbl.setText(f"{v:.3f}V ⚠CRIT")
            elif v < fail_v:
                lbl.setStyleSheet("color:#e67e22; font-weight:bold;")
                lbl.setText(f"{v:.3f}V ⚠LOW")
            else:
                lbl.setStyleSheet(f"color:{color}; font-size:13px;")
                lbl.setText(f"{v:.3f}V")

    def _update_health_panel(self, voltages: list):
        # Use temp engine if no session exists yet
        if not self.engine.session:
            temp = BatteryTestEngine()
            temp.new_session(
                SERIAL_NUMBER_PREFIX,
                self.chemistry_combo.currentData() or DEFAULT_CHEMISTRY,
                DEFAULT_RATED_CAPACITY_AH,
                DEFAULT_PASS_THRESHOLD_PCT
            )
            h = temp.get_current_health_status(voltages)
        else:
            h = self.engine.get_current_health_status(voltages)

        color_map = {
            'NORMAL':   '#27ae60',
            'WARNING':  '#f39c12',
            'ABNORMAL': '#e74c3c',
            'UNKNOWN':  'gray'
        }
        overall = h['overall']
        icon    = "✅" if overall == 'NORMAL' else "⚠"
        self.health_overall.setText(f"{icon} {overall}")
        self.health_overall.setStyleSheet(
            f"font-weight:bold; font-size:14px; "
            f"color:{color_map.get(overall, 'gray')};")

        # Imbalance
        imb = [i for i in h['issues'] if i['type'] == 'IMBALANCE']
        if imb:
            self.health_imbalance.setText(imb[0]['message'])
            self.health_imbalance.setStyleSheet(
                "color:#e74c3c; font-size:12px; font-weight:bold;")
        else:
            self.health_imbalance.setText(
                f"Balanced (spread: {h.get('spread', 0):.3f}V)")
            self.health_imbalance.setStyleSheet("color:#27ae60; font-size:12px;")

        # Critical: check DEAD_CELL then CRITICAL_VOLTAGE
        dead_issues = [i for i in h['issues'] if i['type'] == 'DEAD_CELL']
        crit_issues = [i for i in h['issues'] if i['type'] == 'CRITICAL_VOLTAGE']

        if dead_issues and crit_issues:
            self.health_critical.setText(
                f"{dead_issues[0]['message']}  |  {crit_issues[0]['message']}")
            self.health_critical.setStyleSheet(
                "color:#e74c3c; font-size:12px; font-weight:bold;")
        elif dead_issues:
            self.health_critical.setText(dead_issues[0]['message'])
            self.health_critical.setStyleSheet(
                "color:#e74c3c; font-size:12px; font-weight:bold;")
        elif crit_issues:
            self.health_critical.setText(crit_issues[0]['message'])
            self.health_critical.setStyleSheet(
                "color:#e74c3c; font-size:12px; font-weight:bold;")
        else:
            self.health_critical.setText("All cells OK ✅")
            self.health_critical.setStyleSheet("color:#27ae60; font-size:12px;")

        # Discharge target
        if self.is_testing and self.engine.session:
            avg = h.get('avg_voltage', 0)
            target = self.engine.session.discharge_end_voltage
            self.health_target.setText(
                f"Avg {avg:.3f}V → {avg - target:.3f}V above {target}V min")
            self.health_target.setStyleSheet("color:#2980b9; font-size:12px;")
        elif self.engine.session and \
                self.engine.session.status == TestStatus.COMPLETE:
            self.health_target.setText("✅ BMS protection triggered")
            self.health_target.setStyleSheet(
                "color:#27ae60; font-size:12px; font-weight:bold;")
        else:
            self.health_target.setText("--")
            self.health_target.setStyleSheet("font-size:12px; color:gray;")

    def _update_live_stats(self, voltages: list):
        live = [v for v in voltages if v >= 2.0]
        if not live:
            return
        avg    = sum(live) / len(live)
        min_v  = min(live)
        max_v  = max(live)
        spread = max_v - min_v
        self.stat_labels['Avg Voltage'].setText(f"{avg:.3f}V")
        self.stat_labels['Min Voltage'].setText(f"{min_v:.3f}V")
        self.stat_labels['Max Voltage'].setText(f"{max_v:.3f}V")
        self.stat_labels['Spread'].setText(f"{spread:.3f}V")
        if self.engine.session:
            self.stat_labels['Runtime'].setText(
                self.engine.session.runtime_str)

    def _refresh_result_display(self):
        if not self.engine.session:
            return
        result = self.engine.session.result
        pct    = self.engine.session.capacity_percent
        ah     = self.engine.session.calculated_capacity_ah
        color  = {'PASS': '#27ae60', 'FAIL': '#e74c3c'}.get(
            result.value, '#f39c12')
        self.result_label.setText(result.value)
        self.result_label.setStyleSheet(
            f"font-size:18px; font-weight:bold; color:{color};")
        self.cap_ah_label.setText(f"{ah:.4f} Ah  ({ah*1000:.1f} mAh)")
        self.cap_pct_label.setText(f"{pct:.1f} %")

    def _on_override(self, index: int):
        if not self.engine.session or index == 0:
            return
        reason  = self.override_reason_edit.text().strip()
        new_res = TestResult.PASS if index == 1 else TestResult.FAIL
        self.engine.override_result(new_res, reason)
        self._refresh_result_display()

    def _on_chemistry_changed(self):
        key  = self.chemistry_combo.currentData()
        chem = BATTERY_CHEMISTRIES.get(key, BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY])
        sv   = chem['storage_voltage']
        discharge_end = chem.get('discharge_end_voltage', 3.00)

        # Update storage voltage label (for reference)
        self.storage_label.setText(f"{sv:.2f} V")

        # Update discharge end line on graph (always 3.0V for testing)
        self.storage_line.setValue(discharge_end)
        self.storage_line.label.setPlainText(f"Min {discharge_end}V")

        # Auto-update rated capacity based on chemistry
        rated_ah = chem.get('rated_capacity_ah', DEFAULT_RATED_CAPACITY_AH)
        self.capacity_spin.setValue(rated_ah)

        # Update plot title
        self.plot_widget.setTitle(
            f'Discharge Curves: Cell Voltages + Current ({chem["name"]})',
            color='k', size='13pt'
        )

    # ─────────────────────────────────────────────────────────────────────────
    # EXPORT
    # ─────────────────────────────────────────────────────────────────────────

    def _export_csv(self):
        if not self.engine.session:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV",
            get_csv_filename(self.engine.session),
            "CSV Files (*.csv)")
        if path:
            with open(path, 'w', newline='') as f:
                f.write(generate_csv(self.engine.session))
            self._set_status(f"✅ CSV saved: {path}", "#27ae60")

    def _export_pdf(self):
        if not self.engine.session:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF",
            get_pdf_filename(self.engine.session),
            "PDF Files (*.pdf)")
        if path:
            with open(path, 'wb') as f:
                f.write(generate_pdf(self.engine.session))
            self._set_status(f"✅ PDF saved: {path}", "#27ae60")

    # ─────────────────────────────────────────────────────────────────────────
    # SMALL HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _make_status_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:gray; font-size:13px;")
        return lbl

    def _set_check(self, label: QLabel, passed: bool, text: str):
        label.setText(text)
        label.setStyleSheet(
            f"color:{'#27ae60' if passed else '#e74c3c'}; "
            f"font-size:13px; font-weight:bold;")

    def _set_status(self, msg: str, color: str = "#666"):
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(f"color:{color}; font-weight:bold;")