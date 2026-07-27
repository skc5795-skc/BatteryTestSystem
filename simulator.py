#!/usr/bin/env python3
"""
A-Warrior BMS Simulator for the Battery Test System.

Designed for a fast end-to-end test of:
- BMS connection and pre-check;
- START-button Google Chat notification;
- capacity integration;
- automatic BMS-protection stop;
- automatic CSV/PDF report saving;
- finished-test Google Chat notification.

Default quick-test profile:
- 14S NMC battery;
- simulated rated capacity: 1.0 Ah;
- discharge duration: about 30 seconds;
- discharge current: 120 A;
- final protection flag: 0x0002 (UCP);
- expected result: PASS when the application Rated Capacity is set to 1.0 Ah.

macOS/Linux:
    python simulator.py

The simulator creates a pseudo-terminal automatically and prints the serial
port that the Battery Test System must connect to.

Windows/custom serial port:
    python simulator.py --port COM9

Typical test sequence:
1. Start this simulator.
2. In the Battery Test System, connect to the printed serial port.
3. Set Rated Capacity to 1.0 Ah and Pass Threshold to 95%.
4. Enter the Battery Serial, Cell Batch, Build ID, and Tech Initials.
5. Click START in the application.
6. Return to this terminal and press S, then Enter, to start discharge.
"""

from __future__ import annotations

import argparse
import os
import select
import struct
import sys
import threading
import time
from dataclasses import dataclass
from typing import BinaryIO

try:
    import serial
except ImportError as exc:
    raise SystemExit(
        "pyserial is required. Install it with:\n"
        "    python -m pip install pyserial"
    ) from exc


@dataclass
class SimulationConfig:
    number_of_cells: int = 14
    start_voltage: float = 4.15
    end_voltage: float = 3.01
    rated_capacity_ah: float = 1.0
    duration_seconds: float = 30.0
    cycle_count: int = 5
    temperature_values_c: tuple[float, ...] = (
        25.0,
        25.5,
        24.8,
    )

    @property
    def discharge_current_a(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return (
            self.rated_capacity_ah
            * 3600.0
            / self.duration_seconds
        )


class AWarriorBMSSimulator:
    """Simulate the response frames used by the Battery Test System."""

    START_BYTE = 0xDD
    STOP_BYTE = 0x77
    STATUS_READ = 0xA5

    CMD_BASIC_INFO = 0x03
    CMD_CELL_VOLTAGES = 0x04

    # The application checks bit 1 (0x0002) for UCP protection.
    UCP_PROTECTION_MASK = 0x0002

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.test_running = False
        self.test_complete = False
        self.test_start_time: float | None = None

        self.cell_voltages: list[float] = []
        self.current_ma = 0
        self.soc = 100
        self.residual_capacity_mah = 0
        self.nominal_capacity_mah = 0
        self.protection_status = 0

        self.reset()

    def reset(self):
        """Return the simulated battery to a charged and idle state."""
        self.test_running = False
        self.test_complete = False
        self.test_start_time = None

        # A small balanced variation makes the cell display look realistic.
        centre = (self.config.number_of_cells - 1) / 2.0
        self.cell_voltages = [
            self.config.start_voltage
            + (index - centre) * 0.0008
            for index in range(self.config.number_of_cells)
        ]

        self.current_ma = 0
        self.soc = 100
        self.nominal_capacity_mah = int(
            round(self.config.rated_capacity_ah * 1000.0)
        )
        self.residual_capacity_mah = self.nominal_capacity_mah
        self.protection_status = 0

        print("\n🔄 Simulator reset: battery charged and idle.")

    def start_discharge(self):
        """Start the timed discharge profile."""
        if self.test_running:
            print("ℹ Discharge is already running.")
            return

        if self.test_complete:
            print(
                "ℹ The simulation is complete. Press R then Enter "
                "to reset before starting again."
            )
            return

        self.test_running = True
        self.test_start_time = time.monotonic()
        self.current_ma = -int(
            round(self.config.discharge_current_a * 1000.0)
        )
        self.protection_status = 0

        print(
            "\n🔋 Discharge started: "
            f"{self.config.discharge_current_a:.1f} A for "
            f"{self.config.duration_seconds:.0f} seconds."
        )

    def update_state(self):
        """Update voltage, capacity, current, SOC, and protection state."""
        if not self.test_running or self.test_start_time is None:
            return

        elapsed = time.monotonic() - self.test_start_time
        progress = min(
            1.0,
            max(0.0, elapsed / self.config.duration_seconds),
        )

        base_voltage = (
            self.config.start_voltage
            - (
                self.config.start_voltage
                - self.config.end_voltage
            )
            * progress
        )

        centre = (self.config.number_of_cells - 1) / 2.0
        self.cell_voltages = [
            max(
                self.config.end_voltage,
                base_voltage + (index - centre) * 0.0008,
            )
            for index in range(self.config.number_of_cells)
        ]

        discharged_ah = (
            self.config.rated_capacity_ah * progress
        )
        remaining_ah = max(
            0.0,
            self.config.rated_capacity_ah - discharged_ah,
        )
        self.residual_capacity_mah = int(
            round(remaining_ah * 1000.0)
        )
        self.soc = max(
            0,
            min(
                100,
                int(
                    round(
                        remaining_ah
                        / self.config.rated_capacity_ah
                        * 100.0
                    )
                ),
            ),
        )

        if progress >= 1.0:
            # Hold cells just above the UI's 3.000 V independent cell-cutoff
            # fallback, then use the intended BMS UCP flag to end the test.
            self.cell_voltages = [
                self.config.end_voltage
                + index * 0.0002
                for index in range(self.config.number_of_cells)
            ]
            self.protection_status = self.UCP_PROTECTION_MASK
            self.current_ma = 0
            self.test_running = False
            self.test_complete = True
            print(
                "\n🛑 Simulation complete: UCP protection set "
                "(0x0002), current changed to 0 A."
            )

    @staticmethod
    def calculate_checksum(
        command_code: int,
        data: list[int],
    ) -> tuple[int, int]:
        length = len(data)
        checksum = (
            ~(command_code + length + sum(data)) + 1
        ) & 0xFFFF
        return (
            (checksum >> 8) & 0xFF,
            checksum & 0xFF,
        )

    def build_response(
        self,
        command_code: int,
        data: list[int],
    ) -> bytes:
        checksum_high, checksum_low = self.calculate_checksum(
            command_code,
            data,
        )
        return bytes(
            [
                self.START_BYTE,
                command_code,
                0x00,
                len(data),
                *data,
                checksum_high,
                checksum_low,
                self.STOP_BYTE,
            ]
        )

    def handle_cell_voltages_request(self) -> bytes:
        data: list[int] = []
        for voltage in self.cell_voltages:
            millivolts = int(round(voltage * 1000.0))
            data.extend(
                [
                    (millivolts >> 8) & 0xFF,
                    millivolts & 0xFF,
                ]
            )
        return self.build_response(
            self.CMD_CELL_VOLTAGES,
            data,
        )

    def handle_basic_info_request(self) -> bytes:
        total_voltage_centivolts = int(
            round(sum(self.cell_voltages) * 100.0)
        )

        current_units = int(round(self.current_ma / 10.0))
        current_units = max(
            -32768,
            min(32767, current_units),
        )

        residual_units = max(
            0,
            min(
                65535,
                int(
                    round(
                        self.residual_capacity_mah / 10.0
                    )
                ),
            ),
        )
        nominal_units = max(
            0,
            min(
                65535,
                int(
                    round(
                        self.nominal_capacity_mah / 10.0
                    )
                ),
            ),
        )

        data = bytearray()
        data.extend(
            struct.pack(
                ">H",
                total_voltage_centivolts,
            )
        )
        data.extend(struct.pack(">h", current_units))
        data.extend(struct.pack(">H", residual_units))
        data.extend(struct.pack(">H", nominal_units))
        data.extend(
            struct.pack(
                ">H",
                self.config.cycle_count,
            )
        )

        # Production date and balance status fields are not used by the app.
        data.extend(b"\x00\x00")
        data.extend(b"\x00\x00")
        data.extend(b"\x00\x00")

        data.extend(
            struct.pack(
                ">H",
                self.protection_status,
            )
        )

        data.extend(
            [
                0x10,  # software version
                self.soc,
                0x03,  # FET status
                self.config.number_of_cells,
                len(self.config.temperature_values_c),
            ]
        )

        for temperature_c in self.config.temperature_values_c:
            raw_temperature = int(
                round((temperature_c + 273.15) * 10.0)
            )
            data.extend(
                struct.pack(
                    ">H",
                    raw_temperature,
                )
            )

        return self.build_response(
            self.CMD_BASIC_INFO,
            list(data),
        )


class RequestFrameParser:
    """Extract complete A-Warrior request frames from a byte stream."""

    def __init__(self):
        self.buffer = bytearray()

    def add(self, data: bytes) -> list[bytes]:
        self.buffer.extend(data)
        frames: list[bytes] = []

        while True:
            try:
                start_index = self.buffer.index(
                    AWarriorBMSSimulator.START_BYTE
                )
            except ValueError:
                self.buffer.clear()
                break

            if start_index > 0:
                del self.buffer[:start_index]

            if len(self.buffer) < 4:
                break

            payload_length = self.buffer[3]
            frame_length = 4 + payload_length + 2 + 1

            if len(self.buffer) < frame_length:
                break

            frame = bytes(self.buffer[:frame_length])
            del self.buffer[:frame_length]

            if frame[-1] == AWarriorBMSSimulator.STOP_BYTE:
                frames.append(frame)

        return frames


class SerialTransport:
    """Common byte transport interface for PTY and pyserial modes."""

    display_port: str

    def read_available(self) -> bytes:
        raise NotImplementedError

    def write(self, data: bytes):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


class PtyTransport(SerialTransport):
    """macOS/Linux pseudo-terminal transport without requiring socat."""

    def __init__(self):
        import pty
        import tty

        master_fd, slave_fd = pty.openpty()
        tty.setraw(master_fd)
        tty.setraw(slave_fd)

        self.master_fd = master_fd
        self.slave_fd = slave_fd
        self.display_port = os.ttyname(slave_fd)

        os.set_blocking(self.master_fd, False)

    def read_available(self) -> bytes:
        readable, _, _ = select.select(
            [self.master_fd],
            [],
            [],
            0,
        )
        if not readable:
            return b""

        try:
            return os.read(self.master_fd, 4096)
        except BlockingIOError:
            return b""

    def write(self, data: bytes):
        os.write(self.master_fd, data)

    def close(self):
        for file_descriptor in (
            self.master_fd,
            self.slave_fd,
        ):
            try:
                os.close(file_descriptor)
            except OSError:
                pass


class PySerialTransport(SerialTransport):
    """Transport for a user-supplied serial or virtual COM port."""

    def __init__(self, port: str, baud: int):
        self.serial_connection = serial.Serial(
            port=port,
            baudrate=baud,
            timeout=0.05,
        )
        self.display_port = port

    def read_available(self) -> bytes:
        waiting = self.serial_connection.in_waiting
        if waiting <= 0:
            return b""
        return self.serial_connection.read(waiting)

    def write(self, data: bytes):
        self.serial_connection.write(data)
        self.serial_connection.flush()

    def close(self):
        if self.serial_connection.is_open:
            self.serial_connection.close()


def command_thread(
    simulator: AWarriorBMSSimulator,
    stop_event: threading.Event,
):
    """Accept simple simulator commands without blocking serial responses."""
    print(
        "\nSimulator commands:"
        "\n  S + Enter = start discharge"
        "\n  R + Enter = reset battery"
        "\n  Q + Enter = quit simulator"
    )

    while not stop_event.is_set():
        try:
            command = input("> ").strip().lower()
        except EOFError:
            return

        if command in {"s", "start"}:
            simulator.start_discharge()
        elif command in {"r", "reset"}:
            simulator.reset()
        elif command in {"q", "quit", "exit"}:
            stop_event.set()
            return
        elif command:
            print("Unknown command. Use S, R, or Q.")


def run_server(
    transport: SerialTransport,
    simulator: AWarriorBMSSimulator,
    *,
    baud: int,
):
    print("=" * 68)
    print("BMS SIMULATOR — BATTERY TEST SYSTEM")
    print("=" * 68)
    print(f"\nSerial port for the application: {transport.display_port}")
    print(f"Baud rate: {baud}")
    print(
        "\nApplication quick-test settings:"
        "\n  Chemistry: NMC"
        "\n  Rated Capacity: "
        f"{simulator.config.rated_capacity_ah:.1f} Ah"
        "\n  Pass Threshold: 95%"
    )
    print(
        "\nSequence:"
        "\n  1. Connect the Battery Test System to the port above."
        "\n  2. Confirm the pre-test checks pass."
        "\n  3. Click START in the application."
        "\n  4. Press S then Enter in this terminal."
        "\n  5. Wait for the automatic UCP stop and webhook/report messages."
    )

    stop_event = threading.Event()
    parser = RequestFrameParser()

    threading.Thread(
        target=command_thread,
        args=(simulator, stop_event),
        daemon=True,
    ).start()

    last_status_time = 0.0

    try:
        while not stop_event.is_set():
            simulator.update_state()

            incoming = transport.read_available()
            if incoming:
                for request in parser.add(incoming):
                    # Request format:
                    # DD A5 COMMAND LENGTH ... CHECKSUM CHECKSUM 77
                    if len(request) < 7:
                        continue

                    status = request[1]
                    command = request[2]

                    if status != simulator.STATUS_READ:
                        continue

                    if command == simulator.CMD_CELL_VOLTAGES:
                        response = (
                            simulator.handle_cell_voltages_request()
                        )
                        transport.write(response)

                    elif command == simulator.CMD_BASIC_INFO:
                        response = (
                            simulator.handle_basic_info_request()
                        )
                        transport.write(response)

            now = time.monotonic()
            if (
                simulator.test_running
                and now - last_status_time >= 2.0
            ):
                last_status_time = now
                print(
                    "→ "
                    f"{simulator.current_ma / 1000.0:.1f} A, "
                    f"{simulator.soc}%, "
                    f"min cell "
                    f"{min(simulator.cell_voltages):.3f} V"
                )

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n🛑 Simulator stopped by user.")
    finally:
        stop_event.set()
        transport.close()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "A-Warrior BMS simulator for the Battery Test System."
        )
    )
    parser.add_argument(
        "--port",
        help=(
            "Existing serial/virtual COM port. Omit on macOS/Linux "
            "to create a pseudo-terminal automatically."
        ),
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=9600,
    )
    parser.add_argument(
        "--capacity-ah",
        type=float,
        default=1.0,
        help="Simulated capacity. Default: 1.0 Ah.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Discharge duration in real seconds. Default: 30.",
    )
    return parser.parse_args()


def main():
    args = parse_arguments()

    if args.capacity_ah <= 0:
        raise SystemExit("--capacity-ah must be greater than zero.")
    if args.duration <= 0:
        raise SystemExit("--duration must be greater than zero.")

    config = SimulationConfig(
        rated_capacity_ah=args.capacity_ah,
        duration_seconds=args.duration,
    )

    # Current is encoded as a signed 16-bit number in 10 mA units.
    if config.discharge_current_a > 327.67:
        raise SystemExit(
            "The requested capacity/duration requires "
            f"{config.discharge_current_a:.1f} A, but the protocol "
            "can encode at most 327.67 A. Increase --duration or "
            "reduce --capacity-ah."
        )

    simulator = AWarriorBMSSimulator(config)

    try:
        if args.port:
            transport: SerialTransport = PySerialTransport(
                args.port,
                args.baud,
            )
        elif os.name == "posix":
            transport = PtyTransport()
        else:
            raise SystemExit(
                "Windows requires --port with a virtual COM port."
            )

        run_server(
            transport,
            simulator,
            baud=args.baud,
        )

    except serial.SerialException as exc:
        raise SystemExit(f"Serial error: {exc}") from exc


if __name__ == "__main__":
    main()