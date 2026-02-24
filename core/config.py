
#Battery Test System - Core Configuration ──────────────────────────────────────


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
        'min_start_voltage': 3.00,        # Must be fully charged
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
CELL_IMBALANCE_WARNING_V   = 0.30         # 50mV spread warning
CELL_IMBALANCE_ALERT_V     = 0.50         # 500mV spread = bad cell alert
MIN_START_VOLTAGE          = 3.50         # Fallback min start voltage (per-chemistry used when available)

# ── Serial Communication ──────────────────────────────────────────────────────
DEFAULT_BAUD_RATE    = '9600'
AVAILABLE_BAUD_RATES = ['9600', '19200', '38400', '57600', '115200']
BMS_REQUEST_INTERVAL = 1.0               # 1 second between requests
BMS_RESPONSE_TIMEOUT = 0.5

# ── Data ──────────────────────────────────────────────────────────────────────
MAX_DATA_POINTS = 100000                 # Full discharge session storage

# ── Colors & Branding ────────────────────────────────────────────────────────
# Official Copperstone Technologies Palette
COPPERSTONE_TEAL  = '#064e4a'
COPPERSTONE_GREEN = '#4bb25f'

# ── Cell Colors (14 distinct colors) ─────────────────────────────────────────
# Carefully selected to avoid duplicate shades (e.g., only ONE blue)
# and strictly avoiding Neon Magenta (which is reserved for the Current line).
CELL_COLORS = [
    '#E6194B', # 1. Red
    '#3CB44B', # 2. Green
    '#4363D8', # 3. Blue
    '#F58231', # 4. Orange
    '#911EB4', # 5. Purple
    '#9A6324', # 6. Brown
    '#FA8072', # 7. Salmon/Coral
    '#808000', # 8. Olive
    '#DAA520', # 9. Goldenrod
    '#696969', # 10. Dim Gray
    '#800000', # 11. Maroon
    '#006400', # 12. Dark Green
    '#D2691E', # 13. Chocolate
    '#32CD32'  # 14. Lime Green
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
