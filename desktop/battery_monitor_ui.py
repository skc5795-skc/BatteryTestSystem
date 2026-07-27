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

import pyqtgraph as pg
import serial.tools.list_ports
from PyQt6.QtCore import QRectF, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPixmap, QRegion
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGraphicsPixmapItem,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSizePolicy,
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


DB_FILE = "local_battery_db.json"

# Copperstone visual identity. Teal and green continue to come from config so
# existing application-wide colour settings remain authoritative.
COPPERSTONE_ORANGE = "#F4950D"
COPPERSTONE_DARK_GREY = "#141C2C"
COPPERSTONE_LIGHT_GREY = "#E7ECEC"


class CapacityProgressBar(QProgressBar):
    """Copperstone capacity indicator with a moving white gear."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._measured_ah = 0.0
        self._rated_ah = 0.0
        self._percent = 0.0
        self._gear_pixmap = self._load_capacity_gear()
        self.setRange(0, 1000)
        self.setValue(0)
        self.setTextVisible(False)
        # The widget is taller than the actual progress track so the gear can
        # extend above and below the bar without being clipped.
        self.setMinimumHeight(40)
        self.setMaximumHeight(44)

    @staticmethod
    def _load_capacity_gear() -> QPixmap:
        """Load the white Copperstone gear used by the capacity bar."""
        project_root = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        gear_path = os.path.join(project_root, "gear_watermark.png")
        pixmap = QPixmap(gear_path)
        if pixmap.isNull():
            print(f"Could not load capacity gear: {gear_path}")
        return pixmap

    def set_capacity(self, measured_ah: float, rated_ah: float):
        self._measured_ah = max(0.0, float(measured_ah or 0.0))
        self._rated_ah = max(0.0, float(rated_ah or 0.0))
        if self._rated_ah > 0:
            self._percent = max(0.0, min(100.0, self._measured_ah / self._rated_ah * 100.0))
        else:
            self._percent = 0.0
        self.setValue(round(self._percent * 10))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Draw a slim track inside a taller widget. This gives the gear room
        # to overlap the bar and extend above and below it.
        track_height = 22.0
        bar_rect = QRectF(
            1.0,
            (self.height() - track_height) / 2.0,
            self.width() - 2.0,
            track_height,
        )
        radius = bar_rect.height() / 2.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COPPERSTONE_LIGHT_GREY))
        painter.drawRoundedRect(bar_rect, radius, radius)

        ratio = max(0.0, min(1.0, self._percent / 100.0))
        fill_width = bar_rect.width() * ratio
        if fill_width > 0:
            fill_rect = QRectF(
                bar_rect.left(),
                bar_rect.top(),
                max(fill_width, bar_rect.height()),
                bar_rect.height(),
            )
            fill_rect.setRight(min(fill_rect.right(), bar_rect.right()))
            painter.setBrush(QColor(COPPERSTONE_GREEN))
            painter.drawRoundedRect(fill_rect, radius, radius)

        # Draw the actual Copperstone gear image as a larger marker riding on
        # the leading edge of the progress fill. It intentionally extends
        # above and below the slim progress track.
        gear_size = bar_rect.height() * 1.45

        gear_x = bar_rect.left() + gear_size / 2.0
        if fill_width > gear_size / 2.0:
            gear_x = bar_rect.left() + fill_width
        gear_x = max(
            bar_rect.left() + gear_size / 2.0,
            min(gear_x, bar_rect.right() - gear_size / 2.0),
        )

        gear_rect = QRectF(
            gear_x - gear_size / 2.0,
            bar_rect.center().y() - gear_size / 2.0,
            gear_size,
            gear_size,
        )
        if not self._gear_pixmap.isNull():
            painter.drawPixmap(
                gear_rect,
                self._gear_pixmap,
                QRectF(self._gear_pixmap.rect()),
            )

        if self._rated_ah > 0:
            text = (
                f"{self._measured_ah:.1f} / {self._rated_ah:.1f} Ah "
                f"({self._percent:.0f}%)"
            )
        else:
            text = "0.0 / 0.0 Ah (0%)"

        text_font = QFont(self.font())
        text_font.setBold(True)
        painter.setFont(text_font)
        painter.setPen(QColor(COPPERSTONE_DARK_GREY))
        painter.drawText(bar_rect, Qt.AlignmentFlag.AlignCenter, text)


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
        available = {name.lower(): name for name in QFontDatabase.families()}
        for preferred in preferred_names:
            match = available.get(preferred.lower())
            if match:
                return match
        return preferred_names[-1] if preferred_names else "Segoe UI"

    def _apply_application_style(self):
        self.setStyleSheet(
            f"""
            QMainWindow {{
                background: #FFFFFF;
            }}
            QWidget#centralWidget {{
                background: #FFFFFF;
            }}
            QWidget {{
                font-family: "{self.body_font_family}";
                color: {COPPERSTONE_DARK_GREY};
            }}
            QGroupBox {{
                border: 1px solid #CFD9D8;
                border-radius: 7px;
                margin-top: 10px;
                padding-top: 10px;
                background: #FFFFFF;
                color: {COPPERSTONE_TEAL};
                font-family: "{self.heading_font_family}";
                font-weight: 700;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                top: 3px;
                padding: 0 5px;
                background: #FFFFFF;
            }}
            QLineEdit, QComboBox, QDoubleSpinBox {{
                min-height: 25px;
                border: 1px solid #B9C7C6;
                border-radius: 4px;
                padding: 2px 6px;
                background: #FFFFFF;
                selection-background-color: {COPPERSTONE_TEAL};
                selection-color: #FFFFFF;
            }}
            QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{
                border: 2px solid {COPPERSTONE_TEAL};
            }}
            QPushButton {{
                min-height: 27px;
                border: none;
                border-radius: 4px;
                padding: 3px 10px;
                font-weight: 700;
            }}
            QPushButton:disabled {{
                background: #D7DEDE;
                color: #8B9695;
            }}
            QToolTip {{
                background: #FFFFFF;
                color: {COPPERSTONE_DARK_GREY};
                border: 1px solid {COPPERSTONE_TEAL};
                padding: 4px;
            }}
            """
        )

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

    def _build_logo(self, max_height: int = 44, white: bool = False):
        if not os.path.exists(LOGO_PATH):
            return None
        try:
            logo_label = QLabel()
            pixmap = QPixmap(LOGO_PATH)
            if pixmap.isNull():
                return None

            # Trim transparent padding from the source logo before scaling.
            # This prevents a mathematically centred QLabel from looking
            # visually too high or too low inside the header.
            mask = pixmap.mask()
            if not mask.isNull():
                visible_bounds = QRegion(mask).boundingRect()
                if visible_bounds.isValid() and not visible_bounds.isEmpty():
                    pixmap = pixmap.copy(visible_bounds)

            pixmap = pixmap.scaledToHeight(
                max_height, Qt.TransformationMode.SmoothTransformation
            )

            if white:
                tinted = QPixmap(pixmap.size())
                tinted.fill(Qt.GlobalColor.transparent)
                painter = QPainter(tinted)
                painter.drawPixmap(0, 0, pixmap)
                painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_SourceIn
                )
                painter.fillRect(tinted.rect(), QColor("white"))
                painter.end()
                pixmap = tinted

            logo_label.setPixmap(pixmap)
            logo_label.setFixedSize(pixmap.size())
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_label.setContentsMargins(0, 0, 0, 0)
            logo_label.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
            )
            return logo_label
        except Exception as e:
            print(f"Could not load logo: {e}")
            return None

    def _build_header(self):
        """Build the Copperstone header.

        Layout:
        - left third intentionally blank;
        - Copperstone logo centred in the header;
        - application name and version at the lower right.
        """
        header = QFrame()
        header.setObjectName("appHeader")
        header.setStyleSheet(
            f"QFrame#appHeader {{ background:{COPPERSTONE_TEAL}; "
            "border-radius:7px; }}"
        )
        header.setFixedHeight(100)

        # Three equal columns keep the company logo centred in the complete
        # header rather than centred only in the unused space beside the text.
        layout = QGridLayout(header)
        layout.setContentsMargins(18, 8, 18, 8)
        layout.setHorizontalSpacing(0)
        layout.setVerticalSpacing(0)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)

        # Column 0 is intentionally empty.
        left_spacer = QWidget()
        left_spacer.setStyleSheet("background:transparent;")
        layout.addWidget(left_spacer, 0, 0)

        # Company logo in the visual centre of the complete header.
        logo_widget = self._build_logo(max_height=80, white=True)
        if logo_widget:
            layout.addWidget(
                logo_widget,
                0,
                1,
                Qt.AlignmentFlag.AlignCenter,
            )

        # Product name and version at the bottom-right of the header.
        title = QLabel(f"{APP_NAME} v{APP_VERSION}")
        title_font = QFont(self.heading_font_family, 15)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color:white; background:transparent;")
        title.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
        )

        layout.addWidget(
            title,
            0,
            2,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
        )
        return header

    def setup_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        divider = QFrame()
        divider.setFixedHeight(3)
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
        g = QGroupBox("Test Setup")
        g.setStyleSheet(
            f"QGroupBox {{ color: {COPPERSTONE_TEAL}; font-weight: bold; }}"
        )
        v_main = QVBoxLayout()

        h1 = QHBoxLayout()
        h1.addWidget(QLabel("Battery Serial:"))

        self.serial_edit = QLineEdit(SERIAL_NUMBER_PREFIX)
        self.serial_edit.setMaximumWidth(150)
        self.serial_edit.setFont(QFont("Courier", 11))
        self.serial_edit.textChanged.connect(self._on_serial_changed)
        h1.addWidget(self.serial_edit)

        h1.addWidget(QLabel("Cell Batch #:"))
        self.cell_batch_edit = QLineEdit()
        self.cell_batch_edit.setMaximumWidth(165)
        self.cell_batch_edit.setPlaceholderText("PO-XXXX-XXXX")
        self.cell_batch_edit.setToolTip("Incoming cell batch or purchase order number.")
        h1.addWidget(self.cell_batch_edit)

        h1.addWidget(QLabel("Build ID:"))
        self.build_id_edit = QLineEdit()
        self.build_id_edit.setMaximumWidth(145)
        self.build_id_edit.setPlaceholderText("Rover-12 / Outgoing PO")
        self.build_id_edit.setToolTip(
            "Rover name or outgoing replacement PO. Report-folder integration "
            "will use this value in the reporting phase."
        )
        h1.addWidget(self.build_id_edit)

        h1.addWidget(QLabel("Chemistry:"))
        self.chemistry_combo = QComboBox()
        for key, val in BATTERY_CHEMISTRIES.items():
            full_name = val["name"]
            normalised_name = full_name.upper().replace("-", "")
            if "NMC" in normalised_name:
                display_name = "NMC"
            elif "LIPO" in normalised_name:
                display_name = "LiPo"
            else:
                display_name = full_name
            self.chemistry_combo.addItem(display_name, key)
        self.chemistry_combo.setCurrentIndex(
            self.chemistry_combo.findData(DEFAULT_CHEMISTRY)
        )
        self.chemistry_combo.setFixedWidth(78)
        self.chemistry_combo.setToolTip(
            BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]["name"]
        )
        self.chemistry_combo.currentIndexChanged.connect(
            self._on_chemistry_changed
        )
        h1.addWidget(self.chemistry_combo)

        h1.addWidget(QLabel("Rated Capacity (Ah):"))
        self.capacity_spin = QDoubleSpinBox()
        self.capacity_spin.setRange(1.0, 1000.0)
        self.capacity_spin.setSingleStep(1.0)
        self.capacity_spin.setDecimals(1)
        self.capacity_spin.setValue(DEFAULT_RATED_CAPACITY_AH)
        self.capacity_spin.setFixedWidth(72)
        self.capacity_spin.valueChanged.connect(self._on_capacity_target_changed)
        h1.addWidget(self.capacity_spin)

        h1.addWidget(QLabel("Tech Initials:"))
        self.tech_edit = QLineEdit()
        self.tech_edit.setMaximumWidth(65)
        self.tech_edit.setMaxLength(6)
        self.tech_edit.setPlaceholderText("ABC")
        self.tech_edit.setToolTip(
            "Initials of the technician performing the battery test."
        )
        h1.addWidget(self.tech_edit)

        h1.addStretch()
        v_main.addLayout(h1)

        h2 = QHBoxLayout()
        h2.addWidget(QLabel("MFG Date:"))
        self.mfg_label = QLabel("NEW (Set on Start)")
        self.mfg_label.setStyleSheet(
            f"color:{COPPERSTONE_TEAL}; font-weight:bold;"
        )
        h2.addWidget(self.mfg_label)

        h2.addSpacing(15)
        h2.addWidget(QLabel("Age:"))
        self.age_label = QLabel("0.0 years")
        self.age_label.setStyleSheet(
            f"color:{COPPERSTONE_TEAL}; font-weight:bold;"
        )
        h2.addWidget(self.age_label)

        h2.addSpacing(25)
        h2.addWidget(QLabel("Pass >= :"))
        self.threshold_combo = QComboBox()
        for pct in (80, 85, 90, 95, 100):
            self.threshold_combo.addItem(f"{pct}%", pct)
        self.threshold_combo.setCurrentText(f"{DEFAULT_PASS_THRESHOLD_PCT}%")
        h2.addWidget(self.threshold_combo)

        h2.addSpacing(25)
        h2.addWidget(QLabel("Storage V:"))
        self.storage_label = QLabel(
            f"{BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]['storage_voltage']:.2f} V"
        )
        self.storage_label.setStyleSheet(
            "font-weight:bold; color:#e67e22;"
        )
        h2.addWidget(self.storage_label)
        h2.addStretch()

        h2.addWidget(QLabel("COM Port:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(150)
        self._refresh_ports()
        h2.addWidget(self.port_combo)

        refresh_btn = QPushButton("↻")
        refresh_btn.setMaximumWidth(30)
        refresh_btn.setToolTip("Refresh available COM ports")
        refresh_btn.setStyleSheet(
            f"background:{COPPERSTONE_LIGHT_GREY}; "
            f"color:{COPPERSTONE_TEAL}; font-weight:bold;"
        )
        refresh_btn.clicked.connect(self._refresh_ports)
        h2.addWidget(refresh_btn)

        self.baud_combo = QComboBox()
        self.baud_combo.addItems(AVAILABLE_BAUD_RATES)
        self.baud_combo.setCurrentText(DEFAULT_BAUD_RATE)
        h2.addWidget(self.baud_combo)

        self.connect_btn = QPushButton("Connect BMS")
        self.connect_btn.setStyleSheet(
            f"background:{COPPERSTONE_TEAL}; color:white; font-weight:bold;"
        )
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
                color="#FF00FF",
                width=5,
                style=Qt.PenStyle.SolidLine,
            ),
            name="Current (A)",
        )
        self.current_axis.addItem(self.current_line)
        return self.plot_widget

    def _create_plot_watermark(self):
        """Load the faint Copperstone gear watermark for the plot area."""
        self.plot_watermark = None
        self.plot_watermark_pixmap = QPixmap()

        project_root = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
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

    def _position_plot_watermark(self):
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

    def _init_plot_lines(self, cell_count: int):
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

    def _build_cell_panel(self):
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

    def _build_health_panel(self):
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

    def _build_stats_panel(self):
        g = QGroupBox("Live Information  |  Test Result")
        h = QHBoxLayout()
        h.setSpacing(18)

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
                lbl = QLabel(f"{name}:")
                lbl.setStyleSheet("font-weight:bold;")
                stats_grid.addWidget(lbl, row_idx, col_idx * 2)

                val = QLabel("--")
                val.setStyleSheet(
                    f"color:{COPPERSTONE_TEAL}; "
                    "font-size:13px; font-weight:bold;"
                )
                stats_grid.addWidget(val, row_idx, col_idx * 2 + 1)
                self.stat_labels[name] = val

        stats_w = QWidget()
        stats_w.setLayout(stats_grid)
        h.addWidget(stats_w, stretch=3)

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

        export_h = QHBoxLayout()
        export_h.setSpacing(8)
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

        export_h.addWidget(self.export_csv_btn)
        export_h.addWidget(self.export_pdf_btn)
        result_grid.addLayout(export_h, 4, 0, 1, 2)

        result_w = QWidget()
        result_w.setLayout(result_grid)
        h.addWidget(result_w, stretch=1)

        g.setLayout(h)
        return g

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