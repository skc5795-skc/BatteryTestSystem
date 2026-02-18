"""
Battery Test System - Core Configuration
Shared between Desktop (PyQt6) and Web (Streamlit) apps
"""

# ── Battery Chemistries ───────────────────────────────────────────────────────
BATTERY_CHEMISTRIES = {
    'NMC': {
        'name': 'NMC Prismatic',
        'storage_voltage': 3.60,          # Long-term storage voltage
        'discharge_end_voltage': 3.00,    # Test discharge endpoint (wait for BMS flag)
        'min_cell_voltage': 2.50,
        'max_cell_voltage': 4.20,
        'full_charge_voltage': 4.15,
        'cell_fail_voltage': 3.00,
        'min_start_voltage': 3.60,        # Must be charged to at least storage voltage
        'rated_capacity_ah': 62.0,
    },
    'LiPo': {
        'name': 'LiPo',
        'storage_voltage': 3.80,          # Long-term storage voltage
        'discharge_end_voltage': 3.00,    # Test discharge endpoint (wait for BMS flag)
        'min_cell_voltage': 2.50,
        'max_cell_voltage': 4.20,
        'full_charge_voltage': 4.15,
        'cell_fail_voltage': 3.00,
        'min_start_voltage': 3.80,        # Must be fully charged
        'rated_capacity_ah': 46.0,
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
MIN_START_VOLTAGE          = 3.50         # Fallback min start voltage (per-chemistry used when available)

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

# ── Company Logo ──────────────────────────────────────────────────────────────
# Place your company logo as 'logo.png' in the same directory as main.py
# Recommended size: 200x60 pixels (transparent background)
# If file doesn't exist, app will work without logo
LOGO_PATH     = 'logo.png'