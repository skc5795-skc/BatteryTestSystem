"""
Battery Test System - Desktop Entry Point
"""

import sys
from PyQt6.QtWidgets import QApplication
from desktop.battery_monitor_ui import BatteryTestUI


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')   # Consistent cross-platform look
    window = BatteryTestUI()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
