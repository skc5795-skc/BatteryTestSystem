"""
Battery Test System - Root Entry Point

Usage:
    Desktop app:   python main.py
    Web app:       python main.py --web
                   (then open http://localhost:8501 in browser)
"""

import sys


def run_desktop():
    from PyQt6.QtWidgets import QApplication
    from desktop.battery_monitor_ui import BatteryTestUI
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = BatteryTestUI()
    window.show()
    sys.exit(app.exec())


def run_web():
    import subprocess
    import os
    streamlit_script = os.path.join(
        os.path.dirname(__file__), 'web', 'streamlit_app.py'
    )
    subprocess.run([
        sys.executable, '-m', 'streamlit', 'run', streamlit_script,
        '--server.headless', 'false'
    ])


if __name__ == '__main__':
    if '--web' in sys.argv:
        print("Starting web app at http://localhost:8501 ...")
        run_web()
    else:
        print("Starting desktop app...")
        run_desktop()
