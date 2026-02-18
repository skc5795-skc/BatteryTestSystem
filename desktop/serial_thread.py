"""
Serial Communication Thread - Desktop App
Reads from A-Warrior BMS at 1 second intervals.
"""

import time
import serial
from PyQt6.QtCore import QThread, pyqtSignal

from core.bms_protocol import AWarriorBMS
from core.config import BMS_REQUEST_INTERVAL


class SerialReadThread(QThread):
    """Background thread - reads BMS data without blocking the UI"""

    voltage_received  = pyqtSignal(list, float)   # voltages, timestamp
    info_received     = pyqtSignal(dict)            # basic info dict
    error_occurred    = pyqtSignal(str)
    status_update     = pyqtSignal(str)

    def __init__(self, port: str, baud: int):
        super().__init__()
        self.port        = port
        self.baud        = baud
        self.running     = False
        self.serial_conn = None
        self.start_time  = None
        self.bms         = AWarriorBMS()

    # ── Internal Helpers ──────────────────────────────────────────────────────

    def _open_port(self) -> bool:
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1
            )
            self.serial_conn.reset_input_buffer()
            return True
        except serial.SerialException as e:
            self.error_occurred.emit(f"Failed to open {self.port}: {e}")
            return False

    def _read_frame(self) -> bytes:
        """Read one complete frame from serial port"""
        response   = bytearray()
        start_time = time.time()

        while time.time() - start_time < 0.5:
            if self.serial_conn.in_waiting > 0:
                response.extend(self.serial_conn.read(1))
                if len(response) >= 7 and response[-1] == AWarriorBMS.STOP_BYTE:
                    break

        return bytes(response) if response else b''

    def _send_request(self, request: bytes, label: str) -> bytes:
        """Send a request frame and return the response"""
        try:
            self.serial_conn.write(request)
            print(f"→ Sent {label}: {request.hex(' ')}")
            time.sleep(0.1)

            if self.serial_conn.in_waiting > 0:
                response = self._read_frame()
                if response:
                    print(f"← {label} response ({len(response)}B): {response.hex(' ')}")
                    return response
            else:
                print(f"⚠ No response for {label}")
        except serial.SerialException as e:
            self.error_occurred.emit(f"Serial error: {e}")
        return b''

    # ── Main Loop ─────────────────────────────────────────────────────────────

    def run(self):
        if not self._open_port():
            return

        self.running    = True
        self.start_time = time.time()

        print(f"✓ Serial opened: {self.port} @ {self.baud} baud")
        self.status_update.emit(f"Connected to {self.port}")

        req_counter = 0

        while self.running:
            try:
                loop_start = time.time()

                # ── Cell voltages (every cycle) ───────────────────────────────
                response = self._send_request(
                    self.bms.get_cell_voltages_request(), 'cell_voltages'
                )
                if response and len(response) >= 4 and response[1] == AWarriorBMS.CMD_CELL_VOLTAGES:
                    voltages = self.bms.parse_cell_voltages(response)
                    if voltages:
                        timestamp = time.time() - self.start_time
                        dead = sum(1 for v in voltages if v < 1.0)
                        if dead:
                            print(f"⚠ {dead} dead cell(s) detected")
                        print(f"✓ {len(voltages)} cells parsed")
                        self.voltage_received.emit(voltages, timestamp)

                time.sleep(0.2)

                # ── Basic info (every 2nd cycle = every 2 seconds) ────────────
                if req_counter % 2 == 0:
                    response = self._send_request(
                        self.bms.get_basic_info_request(), 'basic_info'
                    )
                    if response and len(response) >= 4 and response[1] == AWarriorBMS.CMD_BASIC_INFO:
                        info = self.bms.parse_basic_info(response)
                        if info:
                            print(f"✓ Basic info: {info['rsoc_percent']}% SoC, "
                                  f"{info['current_ma']}mA")
                            self.info_received.emit(info)

                req_counter += 1

                # ── Maintain 1 second interval ────────────────────────────────
                elapsed   = time.time() - loop_start
                remaining = BMS_REQUEST_INTERVAL - elapsed
                if remaining > 0:
                    time.sleep(remaining)

            except serial.SerialException as e:
                print(f"✗ Serial error in loop: {e}")
                self.error_occurred.emit(f"Serial error: {e}")
                break
            except Exception as e:
                print(f"✗ Unexpected error: {e}")
                import traceback
                traceback.print_exc()

    def stop(self):
        print("🛑 Stopping serial thread...")
        self.running = False
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            print("✓ Port closed")
        self.wait()