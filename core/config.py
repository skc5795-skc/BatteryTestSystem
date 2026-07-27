"""Battery Test System configuration."""

BATTERY_CHEMISTRIES = {
    "NMC": {
        "name": "NMC Prismatic",
        "storage_voltage": 3.6,
        "discharge_end_voltage": 3.0,
        "min_cell_voltage": 2.5,
        "max_cell_voltage": 4.2,
        "full_charge_voltage": 4.15,
        "cell_fail_voltage": 3.0,
        "min_start_voltage": 3.6,
        "rated_capacity_ah": 62.0,
    },
    "LiPo": {
        "name": "LiPo",
        "storage_voltage": 3.8,
        "discharge_end_voltage": 3.0,
        "min_cell_voltage": 2.5,
        "max_cell_voltage": 4.2,
        "full_charge_voltage": 4.15,
        "cell_fail_voltage": 3.0,
        "min_start_voltage": 3.0,
        "rated_capacity_ah": 46.0,
    },
}

DEFAULT_CHEMISTRY = "NMC"
DEFAULT_RATED_CAPACITY_AH = 62.0
NUMBER_OF_CELLS = 14
SERIAL_NUMBER_PREFIX = "B14S"

DEFAULT_PASS_THRESHOLD_PCT = 95
CELL_IMBALANCE_WARNING_V = 0.3
CELL_IMBALANCE_ALERT_V = 0.5
MIN_START_VOLTAGE = 3.5

DEFAULT_BAUD_RATE = "9600"
AVAILABLE_BAUD_RATES = ["9600", "19200", "38400", "57600", "115200"]
BMS_REQUEST_INTERVAL = 1.0
BMS_RESPONSE_TIMEOUT = 0.5

# Automatic test-stop settings.
# A current within +/-0.10 A is treated as 0 A. The fallback is armed only
# after at least -0.50 A discharge current has been observed.
AUTO_STOP_DISCHARGE_DETECT_MA = -500.0
AUTO_STOP_ZERO_CURRENT_THRESHOLD_MA = 100.0
AUTO_STOP_ZERO_CURRENT_CONFIRMATIONS = 2

MAX_DATA_POINTS = 100000

COPPERSTONE_TEAL = "#064e4a"
COPPERSTONE_GREEN = "#4bb25f"

CELL_COLORS = [
    "#E6194B", "#3CB44B", "#4363D8", "#F58231",
    "#911EB4", "#9A6324", "#FA8072", "#808000",
    "#DAA520", "#696969", "#800000", "#006400",
    "#D2691E", "#32CD32",
]

WINDOW_WIDTH = 1500
WINDOW_HEIGHT = 950
APP_NAME = "Battery Test System"
APP_VERSION = "1.0.1"
LOGO_PATH = "logo.png"

# Google Chat webhook notifications.
# Keep the webhook URL private because it contains authentication parameters.
GOOGLE_CHAT_NOTIFICATIONS_ENABLED = True
GOOGLE_CHAT_WEBHOOK_URL = "https://chat.googleapis.com/v1/spaces/AAQAfgAz6SQ/messages?key=AIzaSyDdI0hCZtE6vySjMm-WEfRq3CPzqKqqsHI&token=YnzmrCgrcnlplrh-jm5DuaGzOSPh9DGcxAZ4WQt7dBA"  # Paste the copied Google Chat webhook URL here.
GOOGLE_CHAT_STATION_NAME = "Battery Station"
GOOGLE_CHAT_TIMEOUT_SECONDS = 8.0
