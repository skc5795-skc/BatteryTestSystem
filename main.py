#------------------Battery Test System - Root Entry Point------------------------
import sys


def run_desktop():
    from PyQt6.QtWidgets import QApplication
    from desktop.battery_monitor_ui import BatteryTestUI
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = BatteryTestUI()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
        print("Starting desktop app...")
        run_desktop()
