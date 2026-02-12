"""
Battery Test System - Core Configuration
Shared between Desktop (PyQt6) and Web (Streamlit) apps
"""

# ── Battery Chemistries ───────────────────────────────────────────────────────
BATTERY_CHEMISTRIES = {
    'NMC': {
        'name': 'NMC Prismatic',
        'storage_voltage': 3.60,
        'min_cell_voltage': 2.50,
        'max_cell_voltage': 4.20,
        'full_charge_voltage': 4.15,
        'cell_fail_voltage': 3.00,
    },
    'LiPo': {
        'name': 'LiPo',
        'storage_voltage': 3.80,
        'min_cell_voltage': 3.00,
        'max_cell_voltage': 4.20,
        'full_charge_voltage': 4.15,
        'cell_fail_voltage': 3.00,
    },
    'LiFePO4': {
        'name': 'LiFePO4',
        'storage_voltage': 3.30,
        'min_cell_voltage': 2.50,
        'max_cell_voltage': 3.65,
        'full_charge_voltage': 3.55,
        'cell_fail_voltage': 2.80,
    },
    'NCA': {
        'name': 'NCA',
        'storage_voltage': 3.67,
        'min_cell_voltage': 2.50,
        'max_cell_voltage': 4.20,
        'full_charge_voltage': 4.10,
        'cell_fail_voltage': 3.00,
    },
}

# ── Default Settings ──────────────────────────────────────────────────────────
DEFAULT_CHEMISTRY         = 'NMC'
DEFAULT_RATED_CAPACITY_AH = 62.0          # 62,000 mAh
NUMBER_OF_CELLS           = 14
SERIAL_NUMBER_PREFIX      = 'B14S'

# ── Pass/Fail Thresholds ──────────────────────────────────────────────────────
DEFAULT_PASS_THRESHOLD_PCT = 95           # Actual must be >= 95% of rated
CELL_IMBALANCE_WARNING_V   = 0.05         # 50mV spread warning
CELL_IMBALANCE_ALERT_V     = 0.50         # 500mV spread = bad cell alert
MIN_START_VOLTAGE          = 3.80         # Cells must start above this to begin test

# ── Serial Communication ──────────────────────────────────────────────────────
DEFAULT_BAUD_RATE    = '9600'
AVAILABLE_BAUD_RATES = ['9600', '19200', '38400', '57600', '115200']
BMS_REQUEST_INTERVAL = 1.0               # 1 second between requests
BMS_RESPONSE_TIMEOUT = 0.5

# ── Data ──────────────────────────────────────────────────────────────────────
MAX_DATA_POINTS = 100000                 # Full discharge session storage

# ── Cell Colors (14 distinct colors) ─────────────────────────────────────────
CELL_COLORS = [
    '#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8',
    '#F7DC6F', '#BB8FCE', '#85C1E2', '#F8B739', '#52B788',
    '#FF85A1', '#5F9EA0', '#DDA15E', '#BC6C25'
]

# ── UI ────────────────────────────────────────────────────────────────────────
WINDOW_WIDTH  = 1500
WINDOW_HEIGHT = 950
APP_NAME      = 'Battery Test System'
APP_VERSION   = '1.0.0'
