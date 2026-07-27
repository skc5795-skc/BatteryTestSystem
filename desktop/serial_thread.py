"""
Serial Communication Thread - Desktop App
Reads from A-Warrior BMS at configured intervals.

"""

from __future__ import annotations

import time
import traceback

import serial
from PyQt6.QtCore import QThread, pyqtSignal

from core.bms_protocol import AWarriorBMS
from core.config import BMS_REQUEST_INTERVAL, BMS_RESPONSE_TIMEOUT


class SerialReadThread(QThread):
    """Read BMS data in the background without blocking the UI."""

    voltage_received = pyqtSignal(list, float)
    info_received = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    status_update = pyqtSignal(str)

    def __init__(self, port: str, baud: int):
        super().__init__()
        self.port = port
        self.baud = baud
        self.running = False
        self.serial_conn: serial.Serial | None = None
        self.start_time: float | None = None
        self.bms = AWarriorBMS()

    def _open_port(self) -> bool:
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.05,
                write_timeout=1.0,
            )
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()
            return True
        except (serial.SerialException, OSError) as error:
            self.error_occurred.emit(
                f"Failed to open {self.port}: {error}"
            )
            return False

    def _close_port(self) -> None:
        """Close the serial port if it is currently open."""
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.close()
                print("✓ Port closed")
            except (serial.SerialException, OSError) as error:
                print(f"⚠ Error while closing port: {error}")

    def _read_frame(self) -> bytes:
        """
        Read one complete BMS frame using the declared payload length.

        Response format:
        START + COMMAND + STATUS + DATA_LENGTH +
        DATA + CHECKSUM_HIGH + CHECKSUM_LOW + STOP

        Total frame length = 7 + DATA_LENGTH.
        """
        if self.serial_conn is None or not self.serial_conn.is_open:
            return b""

        response = bytearray()

        # Some BMS revisions respond more slowly than the original 0.5 s
        # timeout, so never wait less than 1.0 second.
        timeout_seconds = max(float(BMS_RESPONSE_TIMEOUT), 1.0)
        deadline = time.monotonic() + timeout_seconds

        expected_length: int | None = None

        while self.running and time.monotonic() < deadline:
            if self.serial_conn.in_waiting <= 0:
                time.sleep(0.002)
                continue

            received = self.serial_conn.read(1)
            if not received:
                continue

            value = received[0]

            # Ignore noise until the start byte is found.
            if not response:
                if value != AWarriorBMS.START_BYTE:
                    continue

            response.append(value)

            # Byte index 3 contains the declared data payload length.
            if len(response) == 4:
                expected_length = 7 + response[3]

                # Protect against corrupted headers or runaway reads.
                if expected_length < 7 or expected_length > 512:
                    print(
                        "⚠ Invalid declared BMS frame length: "
                        f"{expected_length} bytes"
                    )
                    return b""

            # IMPORTANT:
            # Do not stop merely because 0x77 appears in the payload.
            # Stop only when the full declared frame length is received.
            if (
                expected_length is not None
                and len(response) >= expected_length
            ):
                break

        if not response:
            return b""

        if expected_length is None:
            print(
                "⚠ Incomplete BMS header: "
                f"{response.hex(' ')}"
            )
            return b""

        if len(response) != expected_length:
            print(
                "⚠ Incomplete BMS frame: "
                f"expected {expected_length} bytes, "
                f"received {len(response)} bytes"
            )
            print(f"   Raw: {response.hex(' ')}")
            return b""

        if response[-1] != AWarriorBMS.STOP_BYTE:
            print(
                "⚠ Invalid final BMS stop byte: "
                f"0x{response[-1]:02X}"
            )
            print(f"   Raw: {response.hex(' ')}")
            return b""

        return bytes(response)

    def _send_request(self, request: bytes, label: str) -> bytes:
        """Send one request and return one complete validated-length frame."""
        if self.serial_conn is None or not self.serial_conn.is_open:
            return b""

        try:
            # Remove stale bytes left from a previous incomplete transaction.
            self.serial_conn.reset_input_buffer()

            self.serial_conn.write(request)
            self.serial_conn.flush()
            print(f"→ Sent {label}: {request.hex(' ')}")

            response = self._read_frame()

            if response:
                print(
                    f"← {label} response ({len(response)}B): "
                    f"{response.hex(' ')}"
                )
                return response

            print(f"⚠ No complete response for {label}")
            return b""

        except (serial.SerialException, OSError) as error:
            self.error_occurred.emit(f"Serial error: {error}")
            return b""

    @staticmethod
    def _format_optional(value: object, suffix: str = "") -> str:
        return "unavailable" if value is None else f"{value}{suffix}"

    def run(self):
        if not self._open_port():
            return

        self.running = True
        self.start_time = time.time()

        print(f"✓ Serial opened: {self.port} @ {self.baud} baud")
        self.status_update.emit(f"Connected to {self.port}")

        try:
            while self.running:
                try:
                    loop_start = time.monotonic()

                    response = self._send_request(
                        self.bms.get_cell_voltages_request(),
                        "cell_voltages",
                    )

                    if (
                        response
                        and len(response) >= 4
                        and response[1]
                        == AWarriorBMS.CMD_CELL_VOLTAGES
                    ):
                        voltages = self.bms.parse_cell_voltages(
                            response
                        )
                        if voltages:
                            timestamp = time.time() - (
                                self.start_time or time.time()
                            )
                            dead_count = sum(
                                1
                                for voltage in voltages
                                if voltage < 1.0
                            )
                            if dead_count:
                                print(
                                    f"⚠ {dead_count} dead cell(s) "
                                    "detected"
                                )

                            print(
                                f"✓ {len(voltages)} cells parsed"
                            )
                            self.voltage_received.emit(
                                voltages,
                                timestamp,
                            )

                    time.sleep(0.2)

                    response = self._send_request(
                        self.bms.get_basic_info_request(),
                        "basic_info",
                    )

                    if (
                        response
                        and len(response) >= 4
                        and response[1]
                        == AWarriorBMS.CMD_BASIC_INFO
                    ):
                        declared_payload_length = response[3]
                        print(
                            "ℹ Basic info diagnostics: "
                            f"declared_payload="
                            f"{declared_payload_length}B, "
                            f"frame={response.hex(' ')}"
                        )

                        info = self.bms.parse_basic_info(response)
                        if info:
                            available_fields = sorted(
                                key
                                for key, value in info.items()
                                if value is not None
                                and key not in {"raw_payload_hex"}
                            )
                            print(
                                "✓ Basic info parsed: "
                                f"payload="
                                f"{info.get('payload_length', declared_payload_length)}B, "
                                f"current="
                                f"{self._format_optional(info.get('current_ma'), 'mA')}, "
                                f"SoC="
                                f"{self._format_optional(info.get('rsoc_percent'), '%')}, "
                                f"capacity="
                                f"{self._format_optional(info.get('residual_capacity_mah'), 'mAh')}, "
                                f"fields={available_fields}"
                            )
                            self.info_received.emit(info)
                        else:
                            print(
                                "⚠ Basic info frame could not be "
                                "parsed: "
                                f"{response.hex(' ')}"
                            )

                    elapsed = time.monotonic() - loop_start
                    remaining = BMS_REQUEST_INTERVAL - elapsed
                    if remaining > 0:
                        time.sleep(remaining)

                except (serial.SerialException, OSError) as error:
                    print(f"✗ Serial error in loop: {error}")
                    self.error_occurred.emit(
                        f"Serial error: {error}"
                    )
                    break
                except Exception as error:
                    print(f"✗ Unexpected error: {error}")
                    traceback.print_exc()

        finally:
            self.running = False
            self._close_port()

    def stop(self):
        print("🛑 Stopping serial thread...")
        self.running = False

        # Give the worker time to leave _read_frame() cleanly.
        if not self.wait(2000):
            # Last-resort close to unblock the thread if the driver hangs.
            self._close_port()
            self.wait(1000)