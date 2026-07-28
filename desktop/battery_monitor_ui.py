"""
Battery Test System - Desktop UI (PyQt6)
Production battery discharge test interface.

RECONSTRUCTED SOURCE
This file was manually reconstructed from Python 3.14 bytecode disassembly.
The control flow and constants follow the recovered application, but original
comments, whitespace, local variable names, and some Unicode symbols may differ.
"""

import json
import os
from datetime import datetime

import serial.tools.list_ports
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from core.config import (
    APP_NAME,
    APP_VERSION,
    AUTO_STOP_DISCHARGE_DETECT_MA,
    AUTO_STOP_ZERO_CURRENT_CONFIRMATIONS,
    AUTO_STOP_ZERO_CURRENT_THRESHOLD_MA,
    AVAILABLE_BAUD_RATES,
    BATTERY_CHEMISTRIES,
    CELL_COLORS,
    CELL_IMBALANCE_WARNING_V,
    COPPERSTONE_GREEN,
    COPPERSTONE_TEAL,
    DEFAULT_BAUD_RATE,
    DEFAULT_CHEMISTRY,
    DEFAULT_PASS_THRESHOLD_PCT,
    DEFAULT_RATED_CAPACITY_AH,
    LOGO_PATH,
    NUMBER_OF_CELLS,
    SERIAL_NUMBER_PREFIX,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)
from core.battery_test import BatteryTestEngine, TestResult, TestStatus
from core.chat_notifier import GoogleChatNotifier
from core.report_generator import (
    ReportAutoSaver,
    generate_csv,
    generate_pdf,
    get_csv_filename,
    get_pdf_filename,
)
from desktop.serial_thread import SerialReadThread
from desktop.ui.battery_health_panel import build_battery_health_panel
from desktop.ui.battery_theme import (
    COPPERSTONE_ORANGE,
    apply_application_style,
    resolve_font_family,
)
from desktop.ui.cell_voltage_panel import build_cell_voltage_panel
from desktop.ui.discharge_plot import (
    build_discharge_plot,
    create_plot_watermark,
    initialize_plot_lines,
    position_plot_watermark,
)
from desktop.ui.header import build_header, build_logo
from desktop.ui.live_info_panel import build_live_info_panel
from desktop.ui.pre_test_panel import build_pre_test_panel
from desktop.ui.test_result_panel import build_test_result_panel
from desktop.ui.test_setup_panel import build_test_setup_panel


DB_FILE = "local_battery_db.json"




# Independent cell-voltage fallback for BMS variants that do not expose
# current or protection status reliably. The raw voltage frame is used so the
# cutoff sample is not hidden by the five-sample smoothing window or by the
# voltage rebound that occurs immediately after the inverter switches off.
CELL_CUTOFF_CONFIRMATIONS = 1
VALID_CELL_READING_MIN_V = 2.0


class BatteryTestUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT + 45)

        self.heading_font_family = self._resolve_font_family(
            "Affogato", "Libre Franklin", "Segoe UI"
        )
        self.body_font_family = self._resolve_font_family(
            "Libre Franklin", "Segoe UI", "Arial"
        )
        self.setFont(QFont(self.body_font_family, 10))

        self.local_db = self._load_db()
        self.engine = BatteryTestEngine()
        self.serial_thread = None
        self.is_connected = False
        self.is_testing = False
        self.awaiting_clear = False
        self.pre_check_passed = False
        self.latest_voltages = []
        self.latest_current = 0.0

        # File creation, naming, folder handling, and atomic writes are kept
        # inside report_generator.py. The UI only decides when saving occurs.
        self.report_saver = ReportAutoSaver()
        self.chat_notifier = GoogleChatNotifier()

        # Zero-current auto-stop is armed only after real discharge current
        # has been observed. This prevents a test from stopping while the
        # discharge load is still starting.
        self.discharge_current_seen = False
        self.zero_current_readings = 0
        self.low_cell_cutoff_readings = 0

        self.setup_ui()
        self._apply_application_style()

    @staticmethod
    def _resolve_font_family(*preferred_names: str) -> str:
        return resolve_font_family(*preferred_names)

    def _apply_application_style(self):
        apply_application_style(self)

    def closeEvent(self, event):
        if self.is_testing:
            self.engine.abort_test("Application Closed by User")
            self.is_testing = False
            self.awaiting_clear = True
            self._refresh_result_display()
            self._refresh_final_cell_statistics()

        # Retry auto-save on shutdown if a completed/aborted session exists.
        # No message box is shown while the application is closing.
        if (
            self.engine.session
            and self.engine.session.status
            in (TestStatus.COMPLETE, TestStatus.ABORTED)
        ):
            self._auto_save_reports(show_dialog=False)

        if self.serial_thread:
            self.serial_thread.stop()
        event.accept()

    def _auto_save_reports(
        self,
        *,
        force: bool = False,
        show_dialog: bool = True,
    ) -> bool:
        """Save reports, then notify the Battery Station Alerts space."""
        result = self.report_saver.save(
            self.engine.session,
            force=force,
        )

        # Notify once even when report generation fails, so an interrupted
        # unattended test is still visible to the team.
        notification = self.chat_notifier.send_test_finished(
            self.engine.session,
            report_saved=result.success,
            report_folder=result.folder,
        )

        if not notification.success and not notification.skipped:
            print(
                "Google Chat notification failed: "
                f"{notification.error}"
            )

        if result.skipped:
            return result.success

        if not result.success:
            message = (
                "Automatic report save was incomplete.\n\n"
                + "\n".join(result.errors)
                + (
                    "\n\nFolder:\n" + result.folder
                    if result.folder
                    else ""
                )
            )
            self._set_status(
                "Automatic report save failed",
                "#e74c3c",
            )
            print(message)
            if show_dialog:
                QMessageBox.warning(
                    self,
                    "Automatic Save Failed",
                    message,
                )
            return False

        if not notification.success and not notification.skipped:
            self._set_status(
                "Reports saved; Google Chat notification failed",
                "#f39c12",
            )
        elif notification.skipped:
            self._set_status(
                f"✅ Reports auto-saved: {result.folder}",
                COPPERSTONE_GREEN,
            )
        else:
            self._set_status(
                "✅ Reports saved and Google Chat notified",
                COPPERSTONE_GREEN,
            )

        return True

    def _load_db(self):
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading local DB: {e}")
        return {}

    def _save_db(self):
        try:
            with open(DB_FILE, "w") as f:
                json.dump(self.local_db, f, indent=4)
        except Exception as e:
            print(f"Error saving local DB: {e}")

    def _build_logo(self, max_height: int = 44):
        return build_logo(self, max_height=max_height)

    def _build_header(self):
        return build_header(self)

    def setup_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        divider = QFrame()
        divider.setFixedHeight(5)
        divider.setStyleSheet(
            f"background:{COPPERSTONE_ORANGE}; border:none; border-radius:2px;"
        )

        # Keep the orange divider inside the curved edges of the header.
        divider_row = QHBoxLayout()
        divider_row.setContentsMargins(7, 0, 7, 0)
        divider_row.setSpacing(0)
        divider_row.addWidget(divider)
        root.addLayout(divider_row)

        # Add a small visual gap before the Test Setup section.
        root.addSpacing(5)
        root.addWidget(self._build_top_bar())
        root.addWidget(self._build_pre_check_panel())

        mid = QHBoxLayout()
        mid.setSpacing(8)
        mid.addWidget(self._build_plot(), stretch=5)
        mid.addWidget(self._build_cell_panel(), stretch=1)
        root.addLayout(mid)

        root.addWidget(self._build_health_panel())
        root.addWidget(self._build_stats_panel())

    def _build_top_bar(self):
        return build_test_setup_panel(self)

    def _on_serial_changed(self, text: str):
        serial_no = text.strip()
        entry = self.local_db.get(serial_no, {})

        if isinstance(entry, dict) and entry:
            mfg_date = entry.get("mfg_date", "")
            self.mfg_label.setText(mfg_date or "Unknown")
            self.cell_batch_edit.setText(entry.get("cell_batch", ""))
            self.build_id_edit.setText(entry.get("build_id", ""))

            try:
                mfg_d = datetime.strptime(mfg_date, "%Y-%m-%d")
                days = max(0, (datetime.now() - mfg_d).days)
                self.age_label.setText(f"{days / 365.25:.1f} years")
            except Exception:
                self.age_label.setText("Unknown")
        else:
            self.mfg_label.setText("NEW (Set on Start)")
            self.age_label.setText("0.0 years")
            self.cell_batch_edit.clear()
            self.build_id_edit.clear()

    def _build_pre_check_panel(self):
        return build_pre_test_panel(self)

    def _toggle_test(self):
        if self.is_testing:
            self._stop_test()
        else:
            self._start_test()

    def _set_start_stop_mode(self, testing: bool, enabled: bool = True):
        if testing:
            self.start_btn.setText("■ STOP")
            self.start_btn.setStyleSheet(
                "background:#e74c3c; color:white; "
                "font-size:13px; font-weight:bold;"
            )
            self.start_btn.setEnabled(enabled)
        else:
            self.start_btn.setText("▶ START")
            self.start_btn.setStyleSheet(
                f"background:{COPPERSTONE_GREEN}; color:white; "
                "font-size:13px; font-weight:bold;"
            )
            self.start_btn.setEnabled(enabled)

    def _build_plot(self):
        return build_discharge_plot(self)

    def _create_plot_watermark(self):
        create_plot_watermark(self)

    def _position_plot_watermark(self):
        position_plot_watermark(self)

    def _init_plot_lines(self, cell_count: int):
        initialize_plot_lines(self, cell_count)

    def _build_cell_panel(self):
        return build_cell_voltage_panel(self)

    def _build_health_panel(self):
        return build_battery_health_panel(self)

    def _build_stats_panel(self):
        group = QGroupBox("Live Information  |  Test Result")
        layout = QHBoxLayout()
        layout.setSpacing(18)
        layout.addWidget(build_live_info_panel(self), stretch=3)
        layout.addWidget(build_test_result_panel(self), stretch=1)
        group.setLayout(layout)
        return group

    def _on_capacity_target_changed(self, rated_ah: float):
        if not hasattr(self, "capacity_progress"):
            return
        measured = 0.0
        if self.engine.session:
            measured = self.engine.session.calculated_capacity_ah
        self.capacity_progress.set_capacity(measured, rated_ah)

    def _update_capacity_progress(self, measured_ah: float, rated_ah: float):
        if hasattr(self, "capacity_progress"):
            self.capacity_progress.set_capacity(measured_ah, rated_ah)

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

        port = port_text.split(" - ")[0]
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
            "background:#7f8c8d; color:white; font-weight:bold;"
        )
        self._set_status(f"Connected: {port}", COPPERSTONE_GREEN)

    def _disconnect_bms(self):
        was_testing = self.is_testing

        if was_testing:
            self.engine.abort_test("BMS Disconnected by User")
            self.is_testing = False
            self.awaiting_clear = True

        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None

        self.is_connected = False
        self.pre_check_passed = False
        self.discharge_current_seen = False
        self.zero_current_readings = 0
        self.low_cell_cutoff_readings = 0

        self.connect_btn.setText("Connect BMS")
        self.connect_btn.setStyleSheet(
            f"background:{COPPERSTONE_TEAL}; color:white; font-weight:bold;"
        )
        self._set_start_stop_mode(testing=False, enabled=False)

        if was_testing:
            self.clear_btn.setEnabled(True)
            self.export_csv_btn.setEnabled(True)
            self.export_pdf_btn.setEnabled(True)
            self._refresh_result_display()
            self._refresh_final_cell_statistics()
            self._set_status(
                "Test aborted — BMS disconnected",
                "#e74c3c",
            )
            self._auto_save_reports()
        else:
            self._set_status("Disconnected", "#666")

    def _start_test(self):
        serial_no = self.serial_edit.text().strip()

        if not serial_no or serial_no == SERIAL_NUMBER_PREFIX:
            QMessageBox.warning(
                self,
                "Serial Number Required",
                "Please enter a complete battery serial number.",
            )
            self.serial_edit.setFocus()
            self.serial_edit.setStyleSheet(
                "border: 2px solid red; background: #fff0f0;"
            )
            return

        self.serial_edit.setStyleSheet("")

        entry = self.local_db.get(serial_no)
        if not isinstance(entry, dict):
            entry = {}

        if not entry.get("mfg_date"):
            entry["mfg_date"] = datetime.now().strftime("%Y-%m-%d")
            self.mfg_label.setText(entry["mfg_date"])
            self.age_label.setText("0.0 years")

        cell_batch = self.cell_batch_edit.text().strip()
        build_id = self.build_id_edit.text().strip()
        entry["cell_batch"] = cell_batch
        entry["build_id"] = build_id
        self.local_db[serial_no] = entry
        self._save_db()

        chemistry = self.chemistry_combo.currentData()
        rated_ah = self.capacity_spin.value()
        threshold = self.threshold_combo.currentData()
        tech = self.tech_edit.text().strip()
        mfg_date = self.mfg_label.text()
        age = self.age_label.text()

        self.discharge_current_seen = False
        self.zero_current_readings = 0
        self.low_cell_cutoff_readings = 0

        self.report_saver.reset(build_id)
        self.chat_notifier.reset(build_id)

        self.engine.new_session(
            serial_number=serial_no,
            chemistry=chemistry,
            rated_capacity_ah=rated_ah,
            pass_threshold_pct=threshold,
            tech_initials=tech,
            mfg_date=mfg_date,
            battery_age=age,
            cell_batch=cell_batch,
        )
        self.engine.start_test()

        cell_count = (
            len(self.latest_voltages)
            if self.latest_voltages
            else NUMBER_OF_CELLS
        )
        self._init_plot_lines(cell_count)

        self.is_testing = True
        self.awaiting_clear = False
        self._set_start_stop_mode(testing=True, enabled=True)
        self.clear_btn.setEnabled(False)
        self.export_csv_btn.setEnabled(False)
        self.export_pdf_btn.setEnabled(False)
        self.override_combo.setCurrentIndex(0)
        self.result_label.setText("RUNNING")
        self.result_label.setStyleSheet(
            f"font-size:22px; font-weight:bold; color:{COPPERSTONE_TEAL};"
        )
        self.stop_reason_label.setText("Test in progress.")
        self._update_capacity_progress(0.0, rated_ah)
        self._set_status(
            f"▶ Testing: {serial_no}", COPPERSTONE_GREEN
        )

        start_notification = (
            self.chat_notifier.send_test_started(
                self.engine.session
            )
        )
        if (
            not start_notification.success
            and not start_notification.skipped
        ):
            print(
                "Google Chat start notification failed: "
                f"{start_notification.error}"
            )

    def _stop_test(self):
        self.is_testing = False
        self.discharge_current_seen = False
        self.zero_current_readings = 0
        self.low_cell_cutoff_readings = 0
        self.engine.stop_test("User Stopped Manually")

        self.awaiting_clear = True
        self._set_start_stop_mode(testing=False, enabled=False)
        self.clear_btn.setEnabled(True)
        self.export_csv_btn.setEnabled(True)
        self.export_pdf_btn.setEnabled(True)

        self._refresh_result_display()
        self._refresh_final_cell_statistics()
        result = (
            self.engine.session.result.value
            if self.engine.session
            else "?"
        )
        self._set_status(
            f"■ Stopped — Result: {result}", "#e74c3c"
        )
        self._auto_save_reports()

    def _on_voltage(self, voltages: list, timestamp: float):
        self.latest_voltages = voltages

        if self.is_testing:
            session = self.engine.session
            if session and session.status == TestStatus.TESTING:
                self.engine.record_voltage_sample(
                    voltages, self.latest_current
                )

                if not self.plot_lines:
                    self._init_plot_lines(len(voltages))

                t = session.time_data
                for i, line in enumerate(self.plot_lines):
                    if i < len(session.cell_data) and session.cell_data[i]:
                        line.setData(t, session.cell_data[i])

                current_data = [
                    s.current_ma / 1000.0 for s in session.samples
                ]
                self.current_line.setData(t, current_data)

                ah = session.calculated_capacity_ah
                pct = session.capacity_percent
                self.stat_labels["Runtime"].setText(session.runtime_str)
                self.stat_labels["Measured Capacity"].setText(
                    f"{ah:.4f} Ah"
                )
                self.stat_labels["Capacity %"].setText(f"{pct:.1f}%")
                self._update_capacity_progress(
                    ah, session.rated_capacity_ah
                )

                # Independent inverter-shutdown fallback. Use the raw
                # voltage frame rather than the five-sample average. At the end
                # of discharge, the inverter can switch off and the weak cell
                # can rebound above 3.00 V before a second averaged sample is
                # produced. Recording the sample first preserves the cutoff
                # point in the report, then this check ends the test promptly.
                valid_cells = [
                    (index, voltage)
                    for index, voltage in enumerate(voltages)
                    if voltage >= VALID_CELL_READING_MIN_V
                ]

                if valid_cells:
                    min_index, min_voltage = min(
                        valid_cells, key=lambda item: item[1]
                    )
                    cutoff_voltage = session.discharge_end_voltage

                    if min_voltage <= cutoff_voltage:
                        self.low_cell_cutoff_readings += 1
                    else:
                        self.low_cell_cutoff_readings = 0

                    if (
                        self.low_cell_cutoff_readings
                        >= CELL_CUTOFF_CONFIRMATIONS
                    ):
                        self._complete_auto_stop(
                            "Auto-Stopped (Cell Voltage Reached Discharge Limit)",
                            "🛑 Auto-stop: "
                            f"Cell {min_index + 1} reached "
                            f"{min_voltage:.3f} V "
                            f"(limit {cutoff_voltage:.3f} V).",
                        )
        else:
            self._run_pre_check(voltages)

        self._update_cell_labels(voltages)
        self._update_health_panel(voltages)
        self._update_live_stats(voltages)

    def _complete_auto_stop(self, reason: str, status_message: str):
        """Finish a test after an automatic stop condition."""
        if not self.is_testing:
            return

        self.engine.stop_test(reason)
        self.is_testing = False
        self.awaiting_clear = True
        self.discharge_current_seen = False
        self.zero_current_readings = 0
        self.low_cell_cutoff_readings = 0

        self._set_start_stop_mode(testing=False, enabled=False)
        self.clear_btn.setEnabled(True)
        self.export_csv_btn.setEnabled(True)
        self.export_pdf_btn.setEnabled(True)
        self._refresh_result_display()
        self._refresh_final_cell_statistics()
        self._set_status(status_message, "#e74c3c")
        self._auto_save_reports()

    def _on_info(self, info: dict):
        """Update the UI with whichever Basic Information fields are present."""
        current = info.get("current_ma")

        # Do not replace the last valid current with zero when a partial BMS
        # response omits the current field. A false zero would prematurely
        # trigger auto-stop and would corrupt the integrated Ah calculation.
        if isinstance(current, (int, float)):
            self.latest_current = float(current)

            if current < 0:
                self.stat_labels["Current"].setText(
                    f"{current / 1000.0:.2f} A  (Discharging)"
                )
            elif current > 0:
                self.stat_labels["Current"].setText(
                    f"+{current / 1000.0:.2f} A  (Charging)"
                )
            else:
                self.stat_labels["Current"].setText("0.00 A  (Idle)")
        else:
            self.stat_labels["Current"].setText("Unavailable")

        soc = info.get("rsoc_percent")
        bms_capacity = info.get("residual_capacity_mah")

        self.stat_labels["SoC (BMS)"].setText(
            f"{soc}%" if isinstance(soc, (int, float)) else "Unavailable"
        )
        self.stat_labels["BMS Capacity"].setText(
            f"{bms_capacity} mAh"
            if isinstance(bms_capacity, (int, float))
            else "Unavailable"
        )

        if self.engine.session:
            self.engine.update_bms_info(info)

            if self.is_testing:
                protection_status = info.get("protection_status")
                ucp_active = (
                    isinstance(protection_status, int)
                    and (protection_status & 0x0002) != 0
                )

                # Only evaluate the current fallback when this response
                # actually contains a current value. Partial packets must not
                # be interpreted as 0 A. An exact 0 mA reading stops
                # immediately after discharge has been armed. Small non-zero
                # readings within the tolerance still require consecutive
                # confirmations to reject communication noise.
                exact_zero_current = False
                if isinstance(current, (int, float)):
                    if current <= AUTO_STOP_DISCHARGE_DETECT_MA:
                        self.discharge_current_seen = True
                        self.zero_current_readings = 0
                    elif self.discharge_current_seen and current == 0:
                        exact_zero_current = True
                    elif (
                        self.discharge_current_seen
                        and abs(current)
                        <= AUTO_STOP_ZERO_CURRENT_THRESHOLD_MA
                    ):
                        self.zero_current_readings += 1
                    else:
                        self.zero_current_readings = 0

                if ucp_active:
                    self._complete_auto_stop(
                        "Auto-Stopped (BMS UCP Protection)",
                        "🛑 Auto-stop: "
                        "BMS UCP/undervoltage protection detected!",
                    )
                elif exact_zero_current:
                    self._complete_auto_stop(
                        "Auto-Stopped (Discharge Current Reached 0 A)",
                        "🛑 Auto-stop: discharge current reached 0 A.",
                    )
                elif (
                    self.zero_current_readings
                    >= AUTO_STOP_ZERO_CURRENT_CONFIRMATIONS
                ):
                    self._complete_auto_stop(
                        "Auto-Stopped (Discharge Current Reached 0 A)",
                        "🛑 Auto-stop: discharge current reached 0 A.",
                    )

    def _on_error(self, msg: str):
        self._set_status(f"Error: {msg}", "#e74c3c")
        if self.is_testing:
            self.engine.abort_test(f"Connection Lost: {msg}")
            self.is_testing = False
            self.awaiting_clear = True
            self.discharge_current_seen = False
            self.zero_current_readings = 0
            self.low_cell_cutoff_readings = 0
            self._set_start_stop_mode(testing=False, enabled=False)
            self.clear_btn.setEnabled(True)
            self.export_csv_btn.setEnabled(True)
            self.export_pdf_btn.setEnabled(True)
            self._refresh_result_display()
            self._refresh_final_cell_statistics()
            self._auto_save_reports()

    def _on_status_msg(self, msg: str):
        # The recovered implementation intentionally does nothing.
        return None

    def _run_pre_check(self, voltages: list):
        temp = BatteryTestEngine()
        temp.new_session(
            "",
            self.chemistry_combo.currentData() or DEFAULT_CHEMISTRY,
            self.capacity_spin.value(),
            self.threshold_combo.currentData()
            or DEFAULT_PASS_THRESHOLD_PCT,
        )
        result = temp.run_pre_check(voltages)
        dead_count = sum(1 for v in voltages if v < 2.0)

        if result.all_cells_found and dead_count == 0:
            self._set_check(
                self.check_cells_label,
                True,
                f"{result.cell_count}/{NUMBER_OF_CELLS} cells ✅",
            )
        elif result.all_cells_found and dead_count > 0:
            self.check_cells_label.setText(
                f"{result.cell_count}/{NUMBER_OF_CELLS} "
                f"({dead_count} dead ⚠)"
            )
            self.check_cells_label.setStyleSheet(
                "color:#f39c12; font-size:13px; font-weight:bold;"
            )
        else:
            self._set_check(
                self.check_cells_label,
                False,
                f"{len(voltages)}/{NUMBER_OF_CELLS} cells ❌",
            )

        chem_key = (
            self.chemistry_combo.currentData() or DEFAULT_CHEMISTRY
        )
        chem_cfg = BATTERY_CHEMISTRIES.get(
            chem_key, BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]
        )
        min_start = chem_cfg.get("min_start_voltage", 3.5)

        if result.cells_charged:
            self._set_check(
                self.check_charged_label,
                True,
                f"Min: {result.min_voltage:.3f}V ✅ "
                f"(need ≥ {min_start:.2f}V)",
            )
        else:
            self._set_check(
                self.check_charged_label,
                False,
                f"Min: {result.min_voltage:.3f}V ❌ — "
                f"need ≥ {min_start:.2f}V.",
            )

        if result.cells_balanced:
            self._set_check(
                self.check_balanced_label,
                True,
                f"Spread: {result.spread:.3f}V ✅",
            )
        else:
            self._set_check(
                self.check_balanced_label,
                False,
                f"Spread: {result.spread:.3f}V ❌ — "
                f"need < {CELL_IMBALANCE_WARNING_V:.2f}V",
            )

        self.pre_check_passed = result.passed
        can_start = (
            result.passed
            and self.is_connected
            and not self.is_testing
            and not self.awaiting_clear
        )
        self._set_start_stop_mode(testing=False, enabled=can_start)

    def _update_cell_labels(self, voltages: list):
        chem_key = DEFAULT_CHEMISTRY
        if self.engine.session:
            fail_v = self.engine.session.chemistry_config.get(
                "cell_fail_voltage", 3.0
            )
        else:
            chem_key = (
                self.chemistry_combo.currentData()
                or DEFAULT_CHEMISTRY
            )
            fail_v = BATTERY_CHEMISTRIES[chem_key][
                "cell_fail_voltage"
            ]

        for i, (voltage, label) in enumerate(
            zip(voltages, self.cell_labels)
        ):
            color = CELL_COLORS[i % len(CELL_COLORS)]

            if voltage < 1.0:
                label.setStyleSheet(
                    "color:red; font-weight:bold; "
                    "background-color:#FFE0E0; border-radius:3px;"
                )
                label.setText(f"{voltage:.3f}V ⚠DEAD")
            elif voltage < 2.0:
                label.setStyleSheet(
                    "color:#c0392b; font-weight:bold;"
                )
                label.setText(f"{voltage:.3f}V ⚠CRIT")
            elif voltage < fail_v:
                label.setStyleSheet(
                    "color:#e67e22; font-weight:bold;"
                )
                label.setText(f"{voltage:.3f}V ⚠LOW")
            else:
                label.setStyleSheet(
                    f"color:{color}; font-size:13px;"
                )
                label.setText(f"{voltage:.3f}V")

    def _update_health_panel(self, voltages: list):
        if not self.engine.session:
            temp = BatteryTestEngine()
            temp.new_session(
                "",
                self.chemistry_combo.currentData()
                or DEFAULT_CHEMISTRY,
                0,
                0,
            )
            health = temp.get_current_health_status(voltages)
        else:
            health = self.engine.get_current_health_status(voltages)

        color_map = {
            "NORMAL": COPPERSTONE_GREEN,
            "WARNING": "#f39c12",
            "ABNORMAL": "#e74c3c",
            "UNKNOWN": "gray",
        }

        overall = health["overall"]
        icon = "✅" if overall == "NORMAL" else "⚠"
        self.health_overall.setText(f"{icon} {overall}")
        self.health_overall.setStyleSheet(
            "font-weight:bold; font-size:14px; "
            f"color:{color_map.get(overall, 'gray')};"
        )

        imbalance_issues = [
            issue
            for issue in health["issues"]
            if issue["type"] == "IMBALANCE"
        ]
        if imbalance_issues:
            self.health_imbalance.setText(
                imbalance_issues[0]["message"]
            )
            self.health_imbalance.setStyleSheet(
                "color:#e74c3c; font-size:12px; font-weight:bold;"
            )
        else:
            self.health_imbalance.setText(
                f"Balanced (spread: {health.get('spread', 0):.3f}V)"
            )
            self.health_imbalance.setStyleSheet(
                f"color:{COPPERSTONE_GREEN}; font-size:12px;"
            )

        dead_issues = [
            issue
            for issue in health["issues"]
            if issue["type"] == "DEAD_CELL"
        ]
        critical_issues = [
            issue
            for issue in health["issues"]
            if issue["type"] == "CRITICAL_VOLTAGE"
        ]

        if dead_issues and critical_issues:
            self.health_critical.setText(
                f"{dead_issues[0]['message']}  |  "
                f"{critical_issues[0]['message']}"
            )
            self.health_critical.setStyleSheet(
                "color:#e74c3c; font-size:12px; font-weight:bold;"
            )
        elif dead_issues or critical_issues:
            issue = dead_issues[0] if dead_issues else critical_issues[0]
            self.health_critical.setText(issue["message"])
            self.health_critical.setStyleSheet(
                "color:#e74c3c; font-size:12px; font-weight:bold;"
            )
        else:
            self.health_critical.setText("All cells OK ✅")
            self.health_critical.setStyleSheet(
                f"color:{COPPERSTONE_GREEN}; font-size:12px;"
            )

    def _update_live_stats(self, voltages: list):
        live = [voltage for voltage in voltages if voltage >= 2.0]
        if not live:
            return

        total_v = sum(live)
        avg = total_v / len(live)
        min_v = min(live)
        max_v = max(live)

        self.stat_labels["Total Voltage"].setText(f"{total_v:.2f}V")
        self.stat_labels["Avg Voltage"].setText(f"{avg:.3f}V")
        self.stat_labels["Min Voltage"].setText(f"{min_v:.3f}V")
        self.stat_labels["Max Voltage"].setText(f"{max_v:.3f}V")
        self.stat_labels["Spread"].setText(
            f"{max_v - min_v:.3f}V"
        )

        if self.engine.session:
            self.stat_labels["Runtime"].setText(
                self.engine.session.runtime_str
            )

    def _refresh_final_cell_statistics(self):
        session = self.engine.session
        if not session or not session.final_cell_voltages:
            self.stat_labels["Final Cell Std Dev"].setText("--")
            return

        self.stat_labels["Final Cell Std Dev"].setText(
            f"{session.final_cell_std_dev_mv:.2f} mV"
        )

    def _format_stop_reason(self, reason: str) -> str:
        reason = (reason or "").strip()
        if not reason:
            return ""
        if "BMS UCP" in reason or "BMS" in reason:
            return "Test auto-stopped by BMS protection."
        if "Current Reached 0 A" in reason:
            return "Test auto-stopped when discharge current reached 0 A."
        if "Cell Voltage Reached Discharge Limit" in reason:
            return "Test auto-stopped when a cell reached the discharge limit."
        if "User" in reason or "Manual" in reason:
            return "Test stopped manually by the operator."
        if "Connection Lost" in reason:
            return "Test aborted because the BMS connection was lost."
        if "Application Closed" in reason:
            return "Test aborted because the application was closed."
        return reason

    def _refresh_result_display(self):
        if not self.engine.session:
            return

        session = self.engine.session
        result = session.result
        color = {
            "PASS": COPPERSTONE_GREEN,
            "FAIL": "#e74c3c",
        }.get(result.value, COPPERSTONE_ORANGE)

        self.result_label.setText(result.value)
        self.result_label.setStyleSheet(
            f"font-size:22px; font-weight:bold; color:{color};"
        )
        self.stop_reason_label.setText(
            self._format_stop_reason(session.stop_reason)
        )
        self._update_capacity_progress(
            session.calculated_capacity_ah, session.rated_capacity_ah
        )

    def _on_override(self, index: int):
        if not self.engine.session or index == 0:
            return

        reason = self.override_reason_edit.text().strip()
        new_result = (
            TestResult.PASS if index == 1 else TestResult.FAIL
        )
        self.engine.override_result(new_result, reason)
        self._refresh_result_display()

        # Keep the automatically saved report synchronized with the override.
        if self.engine.session.status in (
            TestStatus.COMPLETE,
            TestStatus.ABORTED,
        ):
            self._auto_save_reports(force=True)

    def _on_chemistry_changed(self):
        key = self.chemistry_combo.currentData()
        chem = BATTERY_CHEMISTRIES.get(
            key, BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]
        )
        storage_voltage = chem["storage_voltage"]
        discharge_end = chem.get("discharge_end_voltage", 3.0)

        self.chemistry_combo.setToolTip(chem["name"])
        self.storage_label.setText(f"{storage_voltage:.2f} V")
        self.storage_line.setValue(discharge_end)
        self.storage_line.label.setPlainText(
            f"Min {discharge_end}V"
        )
        self.capacity_spin.setValue(
            chem.get(
                "rated_capacity_ah",
                DEFAULT_RATED_CAPACITY_AH,
            )
        )
        self.plot_widget.setTitle(
            f"Discharge Curves: Cell Voltages + Current "
            f"({chem['name']})",
            color="k",
            size="13pt",
        )

    def _clear_all(self):
        if self.is_testing:
            return

        self.engine = BatteryTestEngine()
        self.awaiting_clear = False
        self.pre_check_passed = False
        self.latest_voltages = []
        self.latest_current = 0.0
        self.discharge_current_seen = False
        self.zero_current_readings = 0
        self.low_cell_cutoff_readings = 0
        self.report_saver.reset()
        self.chat_notifier.reset()

        self.serial_edit.setText(SERIAL_NUMBER_PREFIX)
        self.cell_batch_edit.clear()
        self.build_id_edit.clear()
        self.tech_edit.clear()
        self.chemistry_combo.setCurrentIndex(
            self.chemistry_combo.findData(DEFAULT_CHEMISTRY)
        )
        self.threshold_combo.setCurrentText(
            f"{DEFAULT_PASS_THRESHOLD_PCT}%"
        )

        self.mfg_label.setText("NEW (Set on Start)")
        self.age_label.setText("0.0 years")

        for label in (
            self.check_cells_label,
            self.check_charged_label,
            self.check_balanced_label,
        ):
            label.setText("Waiting...")
            label.setStyleSheet("color:gray; font-size:13px;")

        for line in self.plot_lines:
            self.plot_widget.removeItem(line)
        self.plot_lines = []
        self.current_line.setData([], [])

        for index, label in enumerate(self.cell_labels):
            label.setText("-.---V")
            label.setStyleSheet(
                f"color:{CELL_COLORS[index % len(CELL_COLORS)]}; "
                "font-size:13px;"
            )

        for label in self.stat_labels.values():
            label.setText("--")

        self.health_overall.setText("-- Waiting --")
        self.health_overall.setStyleSheet(
            "font-weight:bold; font-size:14px; color:gray;"
        )
        for label in (
            self.health_imbalance,
            self.health_critical,
        ):
            label.setText("--")
            label.setStyleSheet("font-size:13px; color:gray;")

        self._update_capacity_progress(0.0, self.capacity_spin.value())

        self.result_label.setText("--")
        self.result_label.setStyleSheet(
            "font-size:22px; font-weight:bold; color:gray;"
        )
        self.stop_reason_label.clear()
        self.override_combo.setCurrentIndex(0)
        self.override_reason_edit.clear()
        self.export_csv_btn.setEnabled(False)
        self.export_pdf_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self._set_start_stop_mode(testing=False, enabled=False)

        status = (
            "Ready for next battery"
            if self.is_connected
            else "Not connected"
        )
        self._set_status(status, "#666")

    def _export_csv(self):
        if not self.engine.session:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save CSV",
            get_csv_filename(self.engine.session),
            "CSV Files (*.csv)",
        )
        if path:
            with open(path, "w", newline="") as f:
                f.write(generate_csv(self.engine.session))
            self._set_status(
                f"✅ CSV saved: {path}", COPPERSTONE_GREEN
            )

    def _export_pdf(self):
        if not self.engine.session:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save PDF",
            get_pdf_filename(self.engine.session),
            "PDF Files (*.pdf)",
        )
        if not path:
            return

        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        temp_path = path + ".tmp"
        try:
            # Build and validate the entire document before touching the
            # destination file. Previously an exception during generate_pdf()
            # could leave an empty PDF that Windows could not open.
            pdf_bytes = generate_pdf(self.engine.session)
            if not isinstance(pdf_bytes, (bytes, bytearray)):
                raise TypeError("PDF generator did not return binary data")
            if not pdf_bytes.startswith(b"%PDF-"):
                raise ValueError("Generated report does not have a PDF header")
            if b"%%EOF" not in pdf_bytes[-2048:]:
                raise ValueError("Generated report is incomplete")

            with open(temp_path, "wb") as file:
                file.write(pdf_bytes)
                file.flush()
                os.fsync(file.fileno())

            os.replace(temp_path, path)
            self._set_status(
                f"✅ PDF saved: {path}", COPPERSTONE_GREEN
            )
        except Exception as exc:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass

            self._set_status("PDF export failed", "#e74c3c")
            QMessageBox.critical(
                self,
                "PDF Export Failed",
                "The PDF report could not be created.\n\n"
                f"Error: {exc}",
            )

    def _make_status_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color:gray; font-size:13px;")
        return label

    def _set_check(self, label: QLabel, passed: bool, text: str):
        label.setText(text)
        label.setStyleSheet(
            f"color:{COPPERSTONE_GREEN if passed else '#e74c3c'}; "
            "font-size:13px; font-weight:bold;"
        )

    def _set_status(self, msg: str, color: str = "#666"):
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(
            f"color:{color}; font-weight:bold;"
        )
