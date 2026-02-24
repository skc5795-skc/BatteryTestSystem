"""
Battery Test System - Desktop UI (PyQt6)
Production battery discharge test interface.
"""

import time
import json
import os
from datetime import datetime
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
    CELL_IMBALANCE_WARNING_V, LOGO_PATH, COPPERSTONE_TEAL, COPPERSTONE_GREEN
)
from core.battery_test import BatteryTestEngine, TestStatus, TestResult
from core.report_generator import (generate_csv, get_csv_filename,
                                    generate_pdf, get_pdf_filename)
from desktop.serial_thread import SerialReadThread

DB_FILE = 'local_battery_db.json'


class BatteryTestUI(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT)

        # ── State ─────────────────────────────────────────────────────────────
        self.local_db         = self._load_db()
        self.engine           = BatteryTestEngine()
        self.serial_thread    = None
        self.is_connected     = False
        self.is_testing       = False
        self.pre_check_passed = False
        self.latest_voltages  = []
        self.latest_current   = 0.0

        self.setup_ui()

    def closeEvent(self, event):
        """Catches if the user exits the app during a test"""
        if self.is_testing:
            self.engine.abort_test("Application Closed by User")
        if self.serial_thread:
            self.serial_thread.stop()
        event.accept()

    # ─────────────────────────────────────────────────────────────────────────
    # DATABASE HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _load_db(self):
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading local DB: {e}")
        return {}

    def _save_db(self):
        try:
            with open(DB_FILE, 'w') as f:
                json.dump(self.local_db, f, indent=4)
        except Exception as e:
            print(f"Error saving local DB: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # UI CONSTRUCTION
    # ─────────────────────────────────────────────────────────────────────────

    def _build_logo(self):
        if not os.path.exists(LOGO_PATH):
            return None
        try:
            logo_label = QLabel()
            pixmap = QPixmap(LOGO_PATH)
            if pixmap.height() > 80:
                pixmap = pixmap.scaledToHeight(80, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(pixmap)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_label.setContentsMargins(0, 0, 0, 0)
            return logo_label
        except Exception as e:
            print(f"⚠ Could not load logo: {e}")
            return None

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(6)

        logo_widget = self._build_logo()
        if logo_widget:
            root.addWidget(logo_widget)

        root.addWidget(self._build_top_bar())
        root.addWidget(self._build_pre_check_panel())

        mid = QHBoxLayout()
        # ── EXPANDED GRAPH HEIGHT ─────────────────────────────────────────────
        # Increased stretch to 5 to massively shrink bottom panel and grow graph
        mid.addWidget(self._build_plot(), stretch=5)
        mid.addWidget(self._build_cell_panel(), stretch=1)
        root.addLayout(mid)

        root.addWidget(self._build_health_panel())
        root.addWidget(self._build_stats_panel())

    # ── Top Bar ───────────────────────────────────────────────────────────────

    def _build_top_bar(self):
        g = QGroupBox("Test Setup")
        g.setStyleSheet(f"QGroupBox {{ color: {COPPERSTONE_TEAL}; font-weight: bold; }}")
        v_main = QVBoxLayout()

        # --- ROW 1: Battery Data ---
        h1 = QHBoxLayout()

        h1.addWidget(QLabel("Battery Serial:"))
        self.serial_edit = QLineEdit(SERIAL_NUMBER_PREFIX)
        self.serial_edit.setMaximumWidth(150)
        self.serial_edit.setFont(QFont('Courier', 11))
        self.serial_edit.textChanged.connect(self._on_serial_changed)
        h1.addWidget(self.serial_edit)

        h1.addWidget(QLabel("Chemistry:"))
        self.chemistry_combo = QComboBox()
        for key, val in BATTERY_CHEMISTRIES.items():
            self.chemistry_combo.addItem(val['name'], key)
        self.chemistry_combo.setCurrentText(BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]['name'])
        self.chemistry_combo.currentIndexChanged.connect(self._on_chemistry_changed)
        h1.addWidget(self.chemistry_combo)

        h1.addWidget(QLabel("Rated Capacity (Ah):"))
        self.capacity_spin = QDoubleSpinBox()
        self.capacity_spin.setRange(1.0, 1000.0)
        self.capacity_spin.setSingleStep(1.0)
        self.capacity_spin.setDecimals(1)
        self.capacity_spin.setValue(DEFAULT_RATED_CAPACITY_AH)
        h1.addWidget(self.capacity_spin)

        h1.addWidget(QLabel("Tech Initials:"))
        self.tech_edit = QLineEdit()
        self.tech_edit.setMaximumWidth(60)
        h1.addWidget(self.tech_edit)

        h1.addStretch()
        v_main.addLayout(h1)

        # --- ROW 2: Database & Connection Data ---
        h2 = QHBoxLayout()

        h2.addWidget(QLabel("MFG Date:"))
        self.mfg_label = QLabel("NEW (Set on Start)")
        self.mfg_label.setStyleSheet(f"color:{COPPERSTONE_TEAL}; font-weight:bold;")
        h2.addWidget(self.mfg_label)

        h2.addSpacing(15)
        h2.addWidget(QLabel("Age:"))
        self.age_label = QLabel("0.0 years")
        self.age_label.setStyleSheet(f"color:{COPPERSTONE_TEAL}; font-weight:bold;")
        h2.addWidget(self.age_label)

        h2.addSpacing(25)
        h2.addWidget(QLabel("Pass >= :"))
        self.threshold_combo = QComboBox()
        for pct in [80, 85, 90, 95, 100]:
            self.threshold_combo.addItem(f"{pct}%", pct)
        self.threshold_combo.setCurrentText(f"{DEFAULT_PASS_THRESHOLD_PCT}%")
        h2.addWidget(self.threshold_combo)

        h2.addSpacing(25)
        h2.addWidget(QLabel("Storage V:"))
        self.storage_label = QLabel(f"{BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]['storage_voltage']:.2f} V")
        self.storage_label.setStyleSheet("font-weight:bold; color:#e67e22;")
        h2.addWidget(self.storage_label)

        h2.addStretch()

        # Connection Controls
        h2.addWidget(QLabel("COM Port:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(150)
        self._refresh_ports()
        h2.addWidget(self.port_combo)

        refresh_btn = QPushButton("↻")
        refresh_btn.setMaximumWidth(28)
        refresh_btn.clicked.connect(self._refresh_ports)
        h2.addWidget(refresh_btn)

        self.baud_combo = QComboBox()
        self.baud_combo.addItems(AVAILABLE_BAUD_RATES)
        self.baud_combo.setCurrentText(DEFAULT_BAUD_RATE)
        h2.addWidget(self.baud_combo)

        self.connect_btn = QPushButton("Connect BMS")
        self.connect_btn.setStyleSheet(f"background:{COPPERSTONE_TEAL}; color:white; font-weight:bold;")
        self.connect_btn.clicked.connect(self._toggle_connection)
        h2.addWidget(self.connect_btn)

        self.status_label = QLabel("Not connected")
        self.status_label.setStyleSheet("color:#666; font-weight:bold;")
        self.status_label.setMinimumWidth(120)
        h2.addWidget(self.status_label)

        v_main.addLayout(h2)
        g.setLayout(v_main)
        return g

    def _on_serial_changed(self, text: str):
        serial = text.strip()
        if serial in self.local_db:
            mfg_date = self.local_db[serial].get('mfg_date', '')
            self.mfg_label.setText(mfg_date)

            try:
                mfg_d = datetime.strptime(mfg_date, '%Y-%m-%d')
                days = (datetime.now() - mfg_d).days
                if days < 0: days = 0

                # Format perfectly as requested: 6 months (182 days) = 0.5 years
                years = days / 365.25
                self.age_label.setText(f"{years:.1f} years")
            except:
                self.age_label.setText("Unknown")
        else:
            self.mfg_label.setText("NEW (Set on Start)")
            self.age_label.setText("0.0 years")

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
            f"background:{COPPERSTONE_GREEN}; color:white; font-size:14px; font-weight:bold;")
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
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', 'Voltage', units='V')
        self.plot_widget.setLabel('bottom', 'Time', units='s')
        self.plot_widget.setTitle('Discharge Curves: Cell Voltages + Current', color='k', size='13pt')
        self.plot_widget.addLegend(offset=(10, 10))
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)

        self.plot_widget.setYRange(2.8, 4.3)

        self.current_axis = pg.ViewBox()
        self.plot_widget.scene().addItem(self.current_axis)
        self.plot_widget.getAxis('right').linkToView(self.current_axis)
        self.current_axis.setXLink(self.plot_widget)
        self.plot_widget.showAxis('right')
        self.plot_widget.getAxis('right').setLabel('Current', units='A')
        self.current_axis.setYRange(-60, 0)

        def update_views():
            self.current_axis.setGeometry(self.plot_widget.getViewBox().sceneBoundingRect())
            self.current_axis.linkedViewChanged(self.plot_widget.getViewBox(), self.current_axis.XAxis)

        update_views()
        self.plot_widget.getViewBox().sigResized.connect(update_views)

        chem = BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]
        discharge_end = chem.get('discharge_end_voltage', 3.00)
        self.storage_line = pg.InfiniteLine(
            pos=discharge_end, angle=0,
            pen=pg.mkPen(color='#e67e22', width=2, style=Qt.PenStyle.DashLine),
            label=f"Min {discharge_end}V",
            labelOpts={'color': '#e67e22', 'position': 0.05}
        )
        self.plot_widget.addItem(self.storage_line)
        self.plot_lines = []

        self.current_line = pg.PlotDataItem(
            pen=pg.mkPen(color='#FF00FF', width=3, style=Qt.PenStyle.SolidLine), # Neon Magenta
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

    # ── Stats + Result Panel ──────────────────────────────────────────────────

    def _build_stats_panel(self):
        g = QGroupBox("Live Statistics  |  Test Result")
        h = QHBoxLayout()

        stats_grid = QGridLayout()
        self.stat_labels = {}
        # Left Side: Compact data readout
        rows = [
            ('Avg Voltage', 'Min Voltage', 'Max Voltage', 'Spread'),
            ('Current',     'Runtime',     'Measured Capacity', 'Capacity %'),
            ('SoC (BMS)',   'BMS Capacity', '', ''),
        ]
        for row_idx, row_items in enumerate(rows):
            for col_idx, name in enumerate(row_items):
                if not name:
                    continue
                lbl = QLabel(f"{name}:")
                lbl.setStyleSheet("font-weight:bold;")
                stats_grid.addWidget(lbl, row_idx, col_idx * 2)
                val = QLabel("--")
                val.setStyleSheet(f"color:{COPPERSTONE_TEAL}; font-size:13px; font-weight:bold;")
                stats_grid.addWidget(val, row_idx, col_idx * 2 + 1)
                self.stat_labels[name] = val

        stats_w = QWidget()
        stats_w.setLayout(stats_grid)
        h.addWidget(stats_w, stretch=3) # Give stats more horizontal room

        # Right Side: Cleaned up Export & Override (Removed redundant capacity text)
        result_grid = QGridLayout()

        result_grid.addWidget(QLabel("Test Result:"), 0, 0)
        self.result_label = QLabel("--")
        self.result_label.setStyleSheet("font-size:18px; font-weight:bold; color:gray;")
        result_grid.addWidget(self.result_label, 0, 1)

        result_grid.addWidget(QLabel("Override:"), 1, 0)
        self.override_combo = QComboBox()
        self.override_combo.addItems(['No override', 'Mark as PASS', 'Mark as FAIL'])
        self.override_combo.currentIndexChanged.connect(self._on_override)
        result_grid.addWidget(self.override_combo, 1, 1)

        self.override_reason_edit = QLineEdit()
        self.override_reason_edit.setPlaceholderText("Override reason (optional)")
        result_grid.addWidget(self.override_reason_edit, 2, 0, 1, 2)

        export_h = QHBoxLayout()
        self.export_csv_btn = QPushButton("Export CSV")
        self.export_csv_btn.setEnabled(False)
        self.export_csv_btn.clicked.connect(self._export_csv)
        self.export_pdf_btn = QPushButton("Export PDF")
        self.export_pdf_btn.setEnabled(False)
        self.export_pdf_btn.clicked.connect(self._export_pdf)
        export_h.addWidget(self.export_csv_btn)
        export_h.addWidget(self.export_pdf_btn)
        result_grid.addLayout(export_h, 3, 0, 1, 2)

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
        self.connect_btn.setStyleSheet("background:#7f8c8d; color:white; font-weight:bold;")
        self._set_status(f"Connected: {port}", COPPERSTONE_GREEN)

    def _disconnect_bms(self):
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None

        self.is_connected     = False
        self.is_testing       = False
        self.pre_check_passed = False

        self.connect_btn.setText("Connect BMS")
        self.connect_btn.setStyleSheet(f"background:{COPPERSTONE_TEAL}; color:white; font-weight:bold;")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self._set_status("Disconnected", "#666")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST CONTROL
    # ─────────────────────────────────────────────────────────────────────────

    def _start_test(self):
        serial_no = self.serial_edit.text().strip()
        if not serial_no or serial_no == SERIAL_NUMBER_PREFIX:
            QMessageBox.warning(self, "Serial Number Required", "Please enter a complete battery serial number.")
            self.serial_edit.setFocus()
            self.serial_edit.setStyleSheet("border: 2px solid red; background: #fff0f0;")
            return
        self.serial_edit.setStyleSheet("")

        # Save to Local DB if new
        if serial_no not in self.local_db:
            mfg = datetime.now().strftime('%Y-%m-%d')
            self.local_db[serial_no] = {'mfg_date': mfg}
            self._save_db()
            self.mfg_label.setText(mfg)
            self.age_label.setText("0.0 years")

        chemistry = self.chemistry_combo.currentData()
        rated_ah  = self.capacity_spin.value()
        threshold = self.threshold_combo.currentData()
        tech      = self.tech_edit.text().strip()
        mfg_date  = self.mfg_label.text()
        age       = self.age_label.text()

        self.engine.new_session(
            serial_number=serial_no,
            chemistry=chemistry,
            rated_capacity_ah=rated_ah,
            pass_threshold_pct=threshold,
            tech_initials=tech,
            mfg_date=mfg_date,
            battery_age=age
        )
        self.engine.start_test()

        cell_count = len(self.latest_voltages) if self.latest_voltages else NUMBER_OF_CELLS
        self._init_plot_lines(cell_count)

        self.is_testing = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.export_csv_btn.setEnabled(False)
        self.export_pdf_btn.setEnabled(False)
        self.override_combo.setCurrentIndex(0)

        self._set_status(f"▶ Testing: {serial_no}", COPPERSTONE_GREEN)

    def _stop_test(self):
        self.is_testing = False
        self.engine.stop_test("User Stopped Manually")

        self.start_btn.setEnabled(self.pre_check_passed and self.is_connected)
        self.stop_btn.setEnabled(False)
        self.export_csv_btn.setEnabled(True)
        self.export_pdf_btn.setEnabled(True)

        self._refresh_result_display()
        result = self.engine.session.result.value if self.engine.session else "?"
        self._set_status(f"■ Stopped — Result: {result}", "#e74c3c")

    # ─────────────────────────────────────────────────────────────────────────
    # DATA HANDLERS
    # ─────────────────────────────────────────────────────────────────────────

    def _on_voltage(self, voltages: list, timestamp: float):
        self.latest_voltages = voltages

        if self.is_testing:
            session = self.engine.session
            if session and session.status == TestStatus.TESTING:
                self.engine.record_voltage_sample(voltages, self.latest_current)

                if not self.plot_lines:
                    self._init_plot_lines(len(voltages))

                t = session.time_data
                for i, line in enumerate(self.plot_lines):
                    if i < len(session.cell_data) and session.cell_data[i]:
                        line.setData(t, session.cell_data[i])

                current_data = [s.current_ma / 1000.0 for s in session.samples]
                self.current_line.setData(t, current_data)

                ah  = session.calculated_capacity_ah
                pct = session.capacity_percent
                self.stat_labels['Runtime'].setText(session.runtime_str)
                self.stat_labels['Measured Capacity'].setText(f"{ah:.4f} Ah")
                self.stat_labels['Capacity %'].setText(f"{pct:.1f}%")
        else:
            self._run_pre_check(voltages)

        self._update_cell_labels(voltages)
        self._update_health_panel(voltages)
        self._update_live_stats(voltages)

    def _on_info(self, info: dict):
        current = info.get('current_ma', 0)
        self.latest_current = current

        if current < 0:
            self.stat_labels['Current'].setText(f"{current/1000.0:.2f} A  (Discharging)")
        elif current > 0:
            self.stat_labels['Current'].setText(f"+{current/1000.0:.2f} A  (Charging)")
        else:
            self.stat_labels['Current'].setText("0.00 A  (Idle)")

        soc = info.get('rsoc_percent', 0)
        bms_cap = info.get('residual_capacity_mah', 0)
        self.stat_labels['SoC (BMS)'].setText(f"{soc}%")
        self.stat_labels['BMS Capacity'].setText(f"{bms_cap} mAh")

        if self.engine.session:
            self.engine.update_bms_info(info)

            if self.is_testing:
                protection_status = info.get('protection_status', 0)
                cell_uv_p = (protection_status & 0x02) != 0

                if cell_uv_p:
                    self.engine.stop_test("Auto-Stopped (BMS Protection)")
                    self.is_testing = False
                    self.stop_btn.setEnabled(False)
                    self.start_btn.setEnabled(False)
                    self.export_csv_btn.setEnabled(True)
                    self.export_pdf_btn.setEnabled(True)
                    self._refresh_result_display()
                    self._set_status("🛑 BMS Protection: Cell undervoltage detected!", "#e74c3c")

    def _on_error(self, msg: str):
        self._set_status(f"Error: {msg}", "#e74c3c")
        if self.is_testing:
            self.engine.abort_test(f"Connection Lost: {msg}")
            self.is_testing = False
            self.stop_btn.setEnabled(False)
            self.start_btn.setEnabled(False)
            self.export_csv_btn.setEnabled(True)
            self.export_pdf_btn.setEnabled(True)
            self._refresh_result_display()

    def _on_status_msg(self, msg: str):
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # PRE-CHECK
    # ─────────────────────────────────────────────────────────────────────────

    def _run_pre_check(self, voltages: list):
        temp = BatteryTestEngine()
        temp.new_session('', self.chemistry_combo.currentData() or DEFAULT_CHEMISTRY,
                         self.capacity_spin.value(), self.threshold_combo.currentData() or DEFAULT_PASS_THRESHOLD_PCT)
        result     = temp.run_pre_check(voltages)
        dead_count = sum(1 for v in voltages if v < 2.0)

        if result.all_cells_found and dead_count == 0:
            self._set_check(self.check_cells_label, True, f"{result.cell_count}/{NUMBER_OF_CELLS} cells ✅")
        elif result.all_cells_found and dead_count > 0:
            self.check_cells_label.setText(f"{result.cell_count}/{NUMBER_OF_CELLS} ({dead_count} dead ⚠)")
            self.check_cells_label.setStyleSheet("color:#f39c12; font-size:13px; font-weight:bold;")
        else:
            self._set_check(self.check_cells_label, False, f"{len(voltages)}/{NUMBER_OF_CELLS} cells ✗")

        chem_key  = self.chemistry_combo.currentData() or DEFAULT_CHEMISTRY
        chem_cfg  = BATTERY_CHEMISTRIES.get(chem_key, BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY])
        min_start = chem_cfg.get('min_start_voltage', 3.50)

        if result.cells_charged:
            self._set_check(self.check_charged_label, True, f"Min: {result.min_voltage:.3f}V ✅ (need ≥ {min_start:.2f}V)")
        else:
            self._set_check(self.check_charged_label, False, f"Min: {result.min_voltage:.3f}V ✗ — need ≥ {min_start:.2f}V.")

        if result.cells_balanced:
            self._set_check(self.check_balanced_label, True, f"Spread: {result.spread:.3f}V ✅")
        else:
            self._set_check(self.check_balanced_label, False, f"Spread: {result.spread:.3f}V ✗ — need < {CELL_IMBALANCE_WARNING_V:.2f}V")

        self.pre_check_passed = result.passed
        self.start_btn.setEnabled(result.passed and self.is_connected and not self.is_testing)

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
                lbl.setStyleSheet("color:red; font-weight:bold; background-color:#FFE0E0; border-radius:3px;")
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
        if not self.engine.session:
            temp = BatteryTestEngine()
            temp.new_session('', self.chemistry_combo.currentData() or DEFAULT_CHEMISTRY, 0, 0)
            h = temp.get_current_health_status(voltages)
        else:
            h = self.engine.get_current_health_status(voltages)

        color_map = {'NORMAL': COPPERSTONE_GREEN, 'WARNING': '#f39c12', 'ABNORMAL': '#e74c3c', 'UNKNOWN': 'gray'}
        overall = h['overall']
        icon    = "✅" if overall == 'NORMAL' else "⚠"
        self.health_overall.setText(f"{icon} {overall}")
        self.health_overall.setStyleSheet(f"font-weight:bold; font-size:14px; color:{color_map.get(overall, 'gray')};")

        imb = [i for i in h['issues'] if i['type'] == 'IMBALANCE']
        if imb:
            self.health_imbalance.setText(imb[0]['message'])
            self.health_imbalance.setStyleSheet("color:#e74c3c; font-size:12px; font-weight:bold;")
        else:
            self.health_imbalance.setText(f"Balanced (spread: {h.get('spread', 0):.3f}V)")
            self.health_imbalance.setStyleSheet(f"color:{COPPERSTONE_GREEN}; font-size:12px;")

        dead_issues = [i for i in h['issues'] if i['type'] == 'DEAD_CELL']
        crit_issues = [i for i in h['issues'] if i['type'] == 'CRITICAL_VOLTAGE']

        if dead_issues and crit_issues:
            self.health_critical.setText(f"{dead_issues[0]['message']}  |  {crit_issues[0]['message']}")
            self.health_critical.setStyleSheet("color:#e74c3c; font-size:12px; font-weight:bold;")
        elif dead_issues or crit_issues:
            iss = dead_issues[0] if dead_issues else crit_issues[0]
            self.health_critical.setText(iss['message'])
            self.health_critical.setStyleSheet("color:#e74c3c; font-size:12px; font-weight:bold;")
        else:
            self.health_critical.setText("All cells OK ✅")
            self.health_critical.setStyleSheet(f"color:{COPPERSTONE_GREEN}; font-size:12px;")

        if self.is_testing and self.engine.session:
            avg = h.get('avg_voltage', 0)
            target = self.engine.session.discharge_end_voltage
            self.health_target.setText(f"Avg {avg:.3f}V → {avg - target:.3f}V above {target}V min")
            self.health_target.setStyleSheet(f"color:{COPPERSTONE_TEAL}; font-size:12px;")
        elif self.engine.session and self.engine.session.status == TestStatus.COMPLETE:
            self.health_target.setText("✅ BMS protection triggered")
            self.health_target.setStyleSheet(f"color:{COPPERSTONE_GREEN}; font-size:12px; font-weight:bold;")
        else:
            self.health_target.setText("--")
            self.health_target.setStyleSheet("font-size:12px; color:gray;")

    def _update_live_stats(self, voltages: list):
        live = [v for v in voltages if v >= 2.0]
        if not live: return
        avg, min_v, max_v = sum(live) / len(live), min(live), max(live)
        self.stat_labels['Avg Voltage'].setText(f"{avg:.3f}V")
        self.stat_labels['Min Voltage'].setText(f"{min_v:.3f}V")
        self.stat_labels['Max Voltage'].setText(f"{max_v:.3f}V")
        self.stat_labels['Spread'].setText(f"{max_v - min_v:.3f}V")
        if self.engine.session:
            self.stat_labels['Runtime'].setText(self.engine.session.runtime_str)

    def _refresh_result_display(self):
        if not self.engine.session: return
        result = self.engine.session.result
        color  = {'PASS': COPPERSTONE_GREEN, 'FAIL': '#e74c3c'}.get(result.value, '#f39c12')
        self.result_label.setText(result.value)
        self.result_label.setStyleSheet(f"font-size:18px; font-weight:bold; color:{color};")

    def _on_override(self, index: int):
        if not self.engine.session or index == 0: return
        reason  = self.override_reason_edit.text().strip()
        new_res = TestResult.PASS if index == 1 else TestResult.FAIL
        self.engine.override_result(new_res, reason)
        self._refresh_result_display()

    def _on_chemistry_changed(self):
        key  = self.chemistry_combo.currentData()
        chem = BATTERY_CHEMISTRIES.get(key, BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY])
        sv   = chem['storage_voltage']
        discharge_end = chem.get('discharge_end_voltage', 3.00)

        self.storage_label.setText(f"{sv:.2f} V")
        self.storage_line.setValue(discharge_end)
        self.storage_line.label.setPlainText(f"Min {discharge_end}V")
        self.capacity_spin.setValue(chem.get('rated_capacity_ah', DEFAULT_RATED_CAPACITY_AH))
        self.plot_widget.setTitle(f'Discharge Curves: Cell Voltages + Current ({chem["name"]})', color='k', size='13pt')

    # ─────────────────────────────────────────────────────────────────────────
    # EXPORT
    # ─────────────────────────────────────────────────────────────────────────

    def _export_csv(self):
        if not self.engine.session: return
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", get_csv_filename(self.engine.session), "CSV Files (*.csv)")
        if path:
            with open(path, 'w', newline='') as f:
                f.write(generate_csv(self.engine.session))
            self._set_status(f"✅ CSV saved: {path}", COPPERSTONE_GREEN)

    def _export_pdf(self):
        if not self.engine.session: return
        path, _ = QFileDialog.getSaveFileName(self, "Save PDF", get_pdf_filename(self.engine.session), "PDF Files (*.pdf)")
        if path:
            with open(path, 'wb') as f:
                f.write(generate_pdf(self.engine.session))
            self._set_status(f"✅ PDF saved: {path}", COPPERSTONE_GREEN)

    def _make_status_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:gray; font-size:13px;")
        return lbl

    def _set_check(self, label: QLabel, passed: bool, text: str):
        label.setText(text)
        label.setStyleSheet(f"color:{COPPERSTONE_GREEN if passed else '#e74c3c'}; font-size:13px; font-weight:bold;")

    def _set_status(self, msg: str, color: str = "#666"):
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(f"color:{color}; font-weight:bold;")
