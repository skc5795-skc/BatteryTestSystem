"""Test setup and BMS connection controls."""

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from core.config import (
    AVAILABLE_BAUD_RATES,
    BATTERY_CHEMISTRIES,
    COPPERSTONE_TEAL,
    DEFAULT_BAUD_RATE,
    DEFAULT_CHEMISTRY,
    DEFAULT_PASS_THRESHOLD_PCT,
    DEFAULT_RATED_CAPACITY_AH,
    SERIAL_NUMBER_PREFIX,
)
from desktop.ui.battery_theme import (
    COPPERSTONE_LIGHT_GREY,
    COPPERSTONE_ORANGE,
)


def build_test_setup_panel(window):
    self = window
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
    self.build_id_edit.setPlaceholderText("Rover/Outgoing PO")
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
