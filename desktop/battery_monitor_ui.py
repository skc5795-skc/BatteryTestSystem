"""
Battery Test System - Desktop UI (PyQt6)
Production battery discharge test interface.
"""

import time
import serial.tools.list_ports
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QGroupBox, QGridLayout, QLineEdit,
    QTextEdit, QSplitter, QMessageBox, QFileDialog, QDoubleSpinBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import pyqtgraph as pg

from core.config import (
    BATTERY_CHEMISTRIES, DEFAULT_CHEMISTRY, DEFAULT_RATED_CAPACITY_AH,
    DEFAULT_PASS_THRESHOLD_PCT, NUMBER_OF_CELLS, CELL_COLORS,
    AVAILABLE_BAUD_RATES, DEFAULT_BAUD_RATE, SERIAL_NUMBER_PREFIX,
    APP_NAME, APP_VERSION, WINDOW_WIDTH, WINDOW_HEIGHT
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

        # Core engine
        self.engine = BatteryTestEngine()
        self.serial_thread: SerialReadThread | None = None
        self.is_connected = False

        # Pre-check state
        self.pre_check_passed = False
        self.latest_voltages  = []
        self.latest_current   = 0.0

        self.setup_ui()

    # ── UI Construction ───────────────────────────────────────────────────────

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(6)

        root.addWidget(self._build_top_bar())
        root.addWidget(self._build_pre_check_panel())

        # Middle: graph + cell voltages side by side
        mid = QHBoxLayout()
        mid.addWidget(self._build_plot(), stretch=3)
        mid.addWidget(self._build_cell_panel(), stretch=1)
        root.addLayout(mid)

        root.addWidget(self._build_health_panel())
        root.addWidget(self._build_stats_panel())

    def _build_top_bar(self):
        g = QGroupBox("Test Setup")
        h = QHBoxLayout()

        # Serial number
        h.addWidget(QLabel("Battery Serial:"))
        self.serial_edit = QLineEdit(SERIAL_NUMBER_PREFIX)
        self.serial_edit.setMaximumWidth(150)
        self.serial_edit.setFont(QFont('Courier', 11))
        h.addWidget(self.serial_edit)

        # Chemistry
        h.addWidget(QLabel("Chemistry:"))
        self.chemistry_combo = QComboBox()
        for key, val in BATTERY_CHEMISTRIES.items():
            self.chemistry_combo.addItem(val['name'], key)
        self.chemistry_combo.setCurrentText(BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]['name'])
        self.chemistry_combo.currentIndexChanged.connect(self._on_chemistry_changed)
        h.addWidget(self.chemistry_combo)

        # Storage voltage (read-only, auto-set from chemistry)
        h.addWidget(QLabel("Storage V:"))
        self.storage_label = QLabel(
            f"{BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]['storage_voltage']:.2f} V"
        )
        self.storage_label.setStyleSheet("font-weight: bold; color: #e67e22;")
        h.addWidget(self.storage_label)

        # Rated capacity
        h.addWidget(QLabel("Rated Capacity (mAh):"))
        self.capacity_spin = QDoubleSpinBox()
        self.capacity_spin.setRange(1.0, 1000.0)
        self.capacity_spin.setSingleStep(1.0)
        self.capacity_spin.setDecimals(1)
        self.capacity_spin.setValue(DEFAULT_RATED_CAPACITY_AH)
        h.addWidget(self.capacity_spin)

        # Pass threshold
        h.addWidget(QLabel("Pass >= :"))
        self.threshold_combo = QComboBox()
        for pct in ['80', '85', '90', '95', '100']:
            self.threshold_combo.addItem(f"{pct}%", int(pct))
        self.threshold_combo.setCurrentText(f"{DEFAULT_PASS_THRESHOLD_PCT}%")
        h.addWidget(self.threshold_combo)

        h.addSpacing(10)

        # COM port
        h.addWidget(QLabel("COM Port:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(180)
        self._refresh_ports()
        h.addWidget(self.port_combo)
        refresh_btn = QPushButton("↻")
        refresh_btn.setMaximumWidth(28)
        refresh_btn.clicked.connect(self._refresh_ports)
        h.addWidget(refresh_btn)

        # Baud
        h.addWidget(QLabel("Baud:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(AVAILABLE_BAUD_RATES)
        self.baud_combo.setCurrentText(DEFAULT_BAUD_RATE)
        h.addWidget(self.baud_combo)

        # Connect / Disconnect
        self.connect_btn = QPushButton("Connect BMS")
        self.connect_btn.setStyleSheet(
            "background:#2980b9; color:white; font-weight:bold;")
        self.connect_btn.clicked.connect(self._connect_bms)
        h.addWidget(self.connect_btn)

        h.addStretch()

        # Status
        self.status_label = QLabel("Not connected")
        self.status_label.setStyleSheet("color:#666; font-weight:bold;")
        h.addWidget(self.status_label)

        g.setLayout(h)
        return g

    def _build_pre_check_panel(self):
        g = QGroupBox("Pre-Test Check")
        h = QHBoxLayout()

        self.check_cells_label    = self._check_label("Waiting...")
        self.check_charged_label  = self._check_label("Waiting...")
        self.check_balanced_label = self._check_label("Waiting...")

        h.addWidget(QLabel("Cells Detected:"))
        h.addWidget(self.check_cells_label)
        h.addSpacing(20)
        h.addWidget(QLabel("Cells Charged:"))
        h.addWidget(self.check_charged_label)
        h.addSpacing(20)
        h.addWidget(QLabel("Cells Balanced:"))
        h.addWidget(self.check_balanced_label)
        h.addStretch()

        # START / STOP test buttons
        self.start_btn = QPushButton("▶  START TEST")
        self.start_btn.setEnabled(False)
        self.start_btn.setMinimumWidth(140)
        self.start_btn.setStyleSheet(
            "background:#27ae60; color:white; font-size:14px; font-weight:bold;")
        self.start_btn.clicked.connect(self._start_test)
        h.addWidget(self.start_btn)

        self.stop_btn = QPushButton("■  STOP TEST")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMinimumWidth(140)
        self.stop_btn.setStyleSheet(
            "background:#e74c3c; color:white; font-size:14px; font-weight:bold;")
        self.stop_btn.clicked.connect(self._stop_test)
        h.addWidget(self.stop_btn)

        g.setLayout(h)
        return g

    def _build_plot(self):
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', 'Voltage', units='V')
        self.plot_widget.setLabel('bottom', 'Time', units='s')
        self.plot_widget.setTitle('Discharge Curves', color='k', size='13pt')
        self.plot_widget.addLegend(offset=(10, 10))
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)

        # Storage voltage dashed line
        chem = BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]
        self.storage_line = pg.InfiniteLine(
            pos=chem['storage_voltage'], angle=0,
            pen=pg.mkPen(color='#e67e22', width=2,
                         style=Qt.PenStyle.DashLine),
            label=f"Storage {chem['storage_voltage']}V",
            labelOpts={'color': '#e67e22', 'position': 0.05}
        )
        self.plot_widget.addItem(self.storage_line)
        self.plot_lines = []

        return self.plot_widget

    def _init_plot_lines(self, cell_count: int):
        for line in self.plot_lines:
            self.plot_widget.removeItem(line)
        self.plot_lines = []
        for i in range(cell_count):
            pen  = pg.mkPen(color=CELL_COLORS[i % len(CELL_COLORS)], width=2)
            line = self.plot_widget.plot([], [], pen=pen, name=f'Cell {i+1}')
            self.plot_lines.append(line)

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

    def _build_health_panel(self):
        g = QGroupBox("Battery Health")
        h = QHBoxLayout()

        h.addWidget(QLabel("Overall:"))
        self.health_overall = QLabel("-- Waiting --")
        self.health_overall.setStyleSheet("font-weight:bold; font-size:14px; color:gray;")
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

    def _build_stats_panel(self):
        g = QGroupBox("Live Statistics  |  Test Result")
        h = QHBoxLayout()

        # Left: live stats
        stats_grid = QGridLayout()
        self.stat_labels = {}
        stats = [
            ('Avg Voltage', 'Min Voltage', 'Max Voltage', 'Spread'),
            ('Current',     'Runtime',     'SoC (BMS)',   'BMS Capacity'),
        ]
        for row, row_items in enumerate(stats):
            for col, name in enumerate(row_items):
                lbl = QLabel(f"{name}:")
                lbl.setStyleSheet("font-weight:bold;")
                stats_grid.addWidget(lbl, row, col*2)
                val = QLabel("--")
                val.setStyleSheet("color:#2980b9; font-size:13px;")
                stats_grid.addWidget(val, row, col*2+1)
                self.stat_labels[name] = val

        stats_widget = QWidget()
        stats_widget.setLayout(stats_grid)
        h.addWidget(stats_widget, stretch=2)

        # Right: capacity + result
        result_grid = QGridLayout()

        result_grid.addWidget(QLabel("Measured Capacity:"), 0, 0)
        self.cap_ah_label = QLabel("0.0000 Ah")
        self.cap_ah_label.setStyleSheet("font-size:15px; font-weight:bold; color:#1a1a2e;")
        result_grid.addWidget(self.cap_ah_label, 0, 1)

        result_grid.addWidget(QLabel("Capacity %:"), 1, 0)
        self.cap_pct_label = QLabel("0.0 %")
        self.cap_pct_label.setStyleSheet("font-size:15px; font-weight:bold; color:#1a1a2e;")
        result_grid.addWidget(self.cap_pct_label, 1, 1)

        result_grid.addWidget(QLabel("Test Result:"), 2, 0)
        self.result_label = QLabel("--")
        self.result_label.setStyleSheet("font-size:18px; font-weight:bold; color:gray;")
        result_grid.addWidget(self.result_label, 2, 1)

        # Override dropdown
        result_grid.addWidget(QLabel("Override:"), 3, 0)
        self.override_combo = QComboBox()
        self.override_combo.addItems(['No override', 'Mark as PASS', 'Mark as FAIL'])
        self.override_combo.currentIndexChanged.connect(self._on_override)
        result_grid.addWidget(self.override_combo, 3, 1)

        # Override reason
        self.override_reason_edit = QLineEdit()
        self.override_reason_edit.setPlaceholderText("Override reason (optional)")
        result_grid.addWidget(self.override_reason_edit, 4, 0, 1, 2)

        # Export buttons
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

        result_widget = QWidget()
        result_widget.setLayout(result_grid)
        h.addWidget(result_widget, stretch=1)

        g.setLayout(h)
        return g

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _check_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:gray; font-size:13px;")
        return lbl

    def _refresh_ports(self):
        self.port_combo.clear()
        for p in serial.tools.list_ports.comports():
            self.port_combo.addItem(f"{p.device} - {p.description}")

    def _on_chemistry_changed(self):
        key  = self.chemistry_combo.currentData()
        chem = BATTERY_CHEMISTRIES.get(key, BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY])
        self.storage_label.setText(f"{chem['storage_voltage']:.2f} V")
        self.storage_line.setValue(chem['storage_voltage'])
        self.storage_line.label.setPlainText(f"Storage {chem['storage_voltage']}V")

    # ── Connection ────────────────────────────────────────────────────────────

    def _connect_bms(self):
        if self.is_connected:
            self._disconnect_bms()
            return

        port_text = self.port_combo.currentText()
        if not port_text:
            self.status_label.setText("No port selected")
            return

        port = port_text.split(' - ')[0]
        baud = int(self.baud_combo.currentText())

        self.serial_thread = SerialReadThread(port, baud)
        self.serial_thread.voltage_received.connect(self._on_voltage)
        self.serial_thread.info_received.connect(self._on_info)
        self.serial_thread.error_occurred.connect(self._on_error)
        self.serial_thread.status_update.connect(self._on_status)
        self.serial_thread.start()

        self.is_connected = True
        self.connect_btn.setText("Disconnect BMS")
        self.connect_btn.setStyleSheet(
            "background:#7f8c8d; color:white; font-weight:bold;")
        self.status_label.setText(f"Connected: {port}")
        self.status_label.setStyleSheet("color:#27ae60; font-weight:bold;")

    def _disconnect_bms(self):
        if self.serial_thread:
            self.serial_thread.stop()

        self.is_connected = False
        self.pre_check_passed = False
        self.connect_btn.setText("Connect BMS")
        self.connect_btn.setStyleSheet(
            "background:#2980b9; color:white; font-weight:bold;")
        self.status_label.setText("Disconnected")
        self.status_label.setStyleSheet("color:#666; font-weight:bold;")
        self.start_btn.setEnabled(False)

    # ── Test Control ──────────────────────────────────────────────────────────

    def _start_test(self):
        serial_no = self.serial_edit.text().strip()
        if not serial_no or serial_no == SERIAL_NUMBER_PREFIX:
            QMessageBox.warning(self, "Serial Number",
                                "Please enter a valid battery serial number.")
            return

        chemistry  = self.chemistry_combo.currentData()
        rated_ah   = self.capacity_spin.value()
        threshold  = self.threshold_combo.currentData()

        # Create session
        self.engine.new_session(serial_no, chemistry, rated_ah, threshold)

        # Initialize plot
        if self.latest_voltages:
            self._init_plot_lines(len(self.latest_voltages))

        self.engine.start_test()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.export_csv_btn.setEnabled(False)
        self.export_pdf_btn.setEnabled(False)
        self.override_combo.setCurrentIndex(0)

        self.status_label.setText(f"Testing: {serial_no}")
        self.status_label.setStyleSheet("color:#27ae60; font-weight:bold;")
        print(f"▶ Test started: {serial_no}")

    def _stop_test(self):
        self.engine.stop_test()
        self.start_btn.setEnabled(self.pre_check_passed)
        self.stop_btn.setEnabled(False)
        self.export_csv_btn.setEnabled(True)
        self.export_pdf_btn.setEnabled(True)

        self._refresh_result_display()
        print(f"■ Test stopped. Result: {self.engine.session.result.value}")

    # ── Data Handlers ─────────────────────────────────────────────────────────

    def _on_voltage(self, voltages: list, timestamp: float):
        self.latest_voltages = voltages

        # Run pre-check always when not testing
        if self.engine.session is None or \
                self.engine.session.status != TestStatus.TESTING:
            self._update_pre_check(voltages)

        # Record data if testing
        if self.engine.session and \
                self.engine.session.status == TestStatus.TESTING:
            self.engine.record_voltage_sample(voltages, self.latest_current)

            # Check if auto-stopped
            if self.engine.session.status == TestStatus.COMPLETE:
                self.start_btn.setEnabled(False)
                self.stop_btn.setEnabled(False)
                self.export_csv_btn.setEnabled(True)
                self.export_pdf_btn.setEnabled(True)
                self._refresh_result_display()
                self.status_label.setText("✅ Discharge complete!")
                self.status_label.setStyleSheet(
                    "color:#27ae60; font-weight:bold;")

        # Update plot
        if self.engine.session and self.engine.session.samples:
            t = self.engine.session.time_data
            for i, line in enumerate(self.plot_lines):
                if i < len(self.engine.session.cell_data):
                    line.setData(t, self.engine.session.cell_data[i])

        # Update cell labels and health
        self._update_cell_labels(voltages)
        self._update_health_panel(voltages)
        self._update_live_stats(voltages)

    def _on_info(self, info: dict):
        self.latest_current = info.get('current_ma', 0.0)

        if self.engine.session:
            self.engine.update_bms_info(info)

        # Update stats
        soc = info.get('rsoc_percent', 0)
        self.stat_labels['SoC (BMS)'].setText(f"{soc}%")

        remaining = info.get('residual_capacity_mah', 0)
        self.stat_labels['BMS Capacity'].setText(f"{remaining} mAh")

        current = info.get('current_ma', 0)
        if current < 0:
            self.stat_labels['Current'].setText(
                f"{current} mA (Discharging)")
        elif current > 0:
            self.stat_labels['Current'].setText(
                f"+{current} mA (Charging)")
        else:
            self.stat_labels['Current'].setText("0 mA (Idle)")

        # Update capacity calculation display
        if self.engine.session:
            ah  = self.engine.session.calculated_capacity_ah
            pct = self.engine.session.capacity_percent
            self.cap_ah_label.setText(
                f"{ah:.4f} Ah  ({ah*1000:.1f} mAh)")
            self.cap_pct_label.setText(f"{pct:.1f} %")
            self.stat_labels['Runtime'].setText(
                self.engine.session.runtime_str)

    def _on_error(self, msg: str):
        self.status_label.setText(f"Error: {msg}")
        self.status_label.setStyleSheet("color:#e74c3c; font-weight:bold;")
        if self.engine.session and \
                self.engine.session.status == TestStatus.TESTING:
            self.engine.abort_test()
            self.stop_btn.setEnabled(False)
            self.start_btn.setEnabled(False)

    def _on_status(self, msg: str):
        print(f"Status: {msg}")

    # ── UI Update Helpers ─────────────────────────────────────────────────────

    def _update_pre_check(self, voltages: list):
        """Run pre-check and update labels. Enable START if passed."""
        if not self.engine.session:
            # Create a temporary session just for pre-check
            self.engine.new_session(
                self.serial_edit.text(),
                self.chemistry_combo.currentData(),
                self.capacity_spin.value(),
                self.threshold_combo.currentData()
            )

        result = self.engine.run_pre_check(voltages)

        def _set(label, passed, text):
            label.setText(text)
            label.setStyleSheet(
                f"color:{'#27ae60' if passed else '#e74c3c'}; "
                f"font-size:13px; font-weight:bold;"
            )

        _set(self.check_cells_label,
             result.all_cells_found,
             f"{result.cell_count}/{NUMBER_OF_CELLS} cells")
        _set(self.check_charged_label,
             result.cells_charged,
             f"Min: {result.min_voltage:.3f}V")
        _set(self.check_balanced_label,
             result.cells_balanced,
             f"Spread: {result.spread:.3f}V")

        self.pre_check_passed = result.passed
        self.start_btn.setEnabled(result.passed and self.is_connected)

    def _update_cell_labels(self, voltages: list):
        live = [v for v in voltages if v >= 2.0]
        avg  = sum(live) / len(live) if live else 0

        for i, (v, lbl) in enumerate(zip(voltages, self.cell_labels)):
            if v < 1.0:
                lbl.setStyleSheet(
                    "color:red; font-weight:bold; background:#FFE0E0;")
                lbl.setText(f"{v:.3f}V ⚠DEAD")
            elif v < 2.5:
                lbl.setStyleSheet("color:#c0392b; font-weight:bold;")
                lbl.setText(f"{v:.3f}V ⚠CRIT")
            elif v < self.engine.session.chemistry_config['cell_fail_voltage'] \
                    if self.engine.session else False:
                lbl.setStyleSheet("color:#e67e22; font-weight:bold;")
                lbl.setText(f"{v:.3f}V ⚠LOW")
            else:
                lbl.setStyleSheet(
                    f"color:{CELL_COLORS[i % len(CELL_COLORS)]}; font-size:13px;")
                lbl.setText(f"{v:.3f}V")

    def _update_health_panel(self, voltages: list):
        if not self.engine.session:
            return

        h = self.engine.get_current_health_status(voltages)

        # Overall
        color_map = {'NORMAL': '#27ae60', 'WARNING': '#f39c12',
                     'ABNORMAL': '#e74c3c', 'UNKNOWN': 'gray'}
        overall = h['overall']
        self.health_overall.setText(
            "✅ NORMAL" if overall == 'NORMAL' else f"⚠ {overall}")
        self.health_overall.setStyleSheet(
            f"font-weight:bold; font-size:14px; "
            f"color:{color_map.get(overall,'gray')};")

        # Imbalance
        imb = [i for i in h['issues'] if i['type'] == 'IMBALANCE']
        if imb:
            self.health_imbalance.setText(imb[0]['message'])
            self.health_imbalance.setStyleSheet("color:#e74c3c; font-size:12px;")
        else:
            spread = h.get('spread', 0)
            self.health_imbalance.setText(f"Balanced (spread: {spread:.3f}V)")
            self.health_imbalance.setStyleSheet("color:#27ae60; font-size:12px;")

        # Critical
        crit = [i for i in h['issues'] if i['type'] == 'CRITICAL_VOLTAGE']
        if crit:
            self.health_critical.setText(crit[0]['message'])
            self.health_critical.setStyleSheet("color:#e74c3c; font-size:12px;")
        else:
            self.health_critical.setText("All cells OK")
            self.health_critical.setStyleSheet("color:#27ae60; font-size:12px;")

        # Discharge target
        if self.engine.session.status == TestStatus.TESTING:
            avg = h.get('avg_voltage', 0)
            sv  = self.engine.session.storage_voltage
            rem = avg - sv
            self.health_target.setText(
                f"Avg {avg:.3f}V  →  {rem:.3f}V above {sv}V target")
            self.health_target.setStyleSheet("color:#2980b9; font-size:12px;")
        elif self.engine.session.status == TestStatus.COMPLETE:
            self.health_target.setText("✅ Target reached")
            self.health_target.setStyleSheet(
                "color:#27ae60; font-size:12px; font-weight:bold;")

    def _update_live_stats(self, voltages: list):
        live = [v for v in voltages if v >= 2.0]
        if not live:
            return
        self.stat_labels['Avg Voltage'].setText(
            f"{sum(live)/len(live):.3f}V")
        self.stat_labels['Min Voltage'].setText(f"{min(live):.3f}V")
        self.stat_labels['Max Voltage'].setText(f"{max(live):.3f}V")
        self.stat_labels['Spread'].setText(
            f"{max(live)-min(live):.3f}V")
        if self.engine.session:
            self.stat_labels['Runtime'].setText(
                self.engine.session.runtime_str)

    def _refresh_result_display(self):
        if not self.engine.session:
            return
        result = self.engine.session.result
        color  = {'PASS': '#27ae60', 'FAIL': '#e74c3c'}.get(
            result.value, '#f39c12')
        self.result_label.setText(result.value)
        self.result_label.setStyleSheet(
            f"font-size:18px; font-weight:bold; color:{color};")

    def _on_override(self, index: int):
        if not self.engine.session:
            return
        reason = self.override_reason_edit.text().strip()
        if index == 1:
            self.engine.override_result(TestResult.PASS, reason)
        elif index == 2:
            self.engine.override_result(TestResult.FAIL, reason)
        if index > 0:
            self._refresh_result_display()

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_csv(self):
        if not self.engine.session:
            return
        filename = get_csv_filename(self.engine.session)
        path, _  = QFileDialog.getSaveFileName(
            self, "Save CSV", filename, "CSV Files (*.csv)"
        )
        if path:
            with open(path, 'w', newline='') as f:
                f.write(generate_csv(self.engine.session))
            self.status_label.setText(f"✅ CSV saved: {path}")

    def _export_pdf(self):
        if not self.engine.session:
            return
        filename = get_pdf_filename(self.engine.session)
        path, _  = QFileDialog.getSaveFileName(
            self, "Save PDF", filename, "PDF Files (*.pdf)"
        )
        if path:
            with open(path, 'wb') as f:
                f.write(generate_pdf(self.engine.session))
            self.status_label.setText(f"✅ PDF saved: {path}")
