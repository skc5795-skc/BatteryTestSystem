#!/usr/bin/env python3
"""
BMS Simulator for Battery Test System
Simulates a complete discharge test in ~30 seconds for testing reports.

Usage:
    python simulator.py

The simulator creates a virtual serial port that the Battery Test System
can connect to. It simulates:
- 14 cells starting at 4.15V (fully charged)
- Discharge at 15A constant current
- 60 minutes of runtime compressed to 30 seconds
- BMS protection trigger (cell_uv_p) when cells reach 3.0V
- Capacity: ~60Ah (will PASS with 95% threshold)

IMPORTANT: Install pyserial first:
    pip install pyserial
"""

import time
import struct
import threading
import serial
import serial.tools.list_ports


class AWarriorBMSSimulator:
    """Simulates A-Warrior BMS responses"""

    START_BYTE = 0xDD
    STOP_BYTE = 0x77
    CMD_BASIC_INFO = 0x03
    CMD_CELL_VOLTAGES = 0x04

    def __init__(self):
        # Simulation state
        self.test_running = False
        self.test_start_time = None

        # Battery state (14S NMC, 62Ah rated)
        self.num_cells = 14
        self.cell_voltages = [4.15] * self.num_cells  # Start fully charged
        self.current_ma = 0  # Idle initially
        self.soc = 100
        self.residual_capacity_mah = 62000
        self.nominal_capacity_mah = 62000
        self.cycle_count = 5
        self.protection_status = 0x0000
        self.temperatures = [25.0, 25.5, 24.8]  # 3 temperature sensors

    def start_discharge(self):
        """Start simulated discharge"""
        if not self.test_running:
            self.test_running = True
            self.test_start_time = time.time()
            self.current_ma = -15000  # -15A discharge
            print("🔋 Simulator: Discharge started at -15A")

    def update_state(self):
        """Update battery state based on elapsed time"""
        if not self.test_running:
            return

        # Simulate 60 minutes in 30 seconds (120x speed)
        elapsed_real = time.time() - self.test_start_time
        elapsed_sim = elapsed_real * 120  # 120x speed

        # Discharge curve: 4.15V -> 3.0V over 60 minutes
        # Using simple linear discharge for testing
        voltage_drop_per_min = (4.15 - 3.00) / 60.0
        voltage_drop = voltage_drop_per_min * (elapsed_sim / 60.0)

        for i in range(self.num_cells):
            # Add small variance between cells
            variance = 0.01 * (i - 7) / 7  # -0.01V to +0.01V
            self.cell_voltages[i] = max(3.00, 4.15 - voltage_drop + variance)

        # Update capacity (discharge at 15A)
        ah_discharged = (elapsed_sim / 3600.0) * 15.0
        self.residual_capacity_mah = max(0, self.nominal_capacity_mah - int(ah_discharged * 1000))

        # Update SoC
        self.soc = int((self.residual_capacity_mah / self.nominal_capacity_mah) * 100)

        # Trigger protection when cells reach 3.0V
        if min(self.cell_voltages) <= 3.0:
            self.protection_status = 0x0001  # Bit 0 = cell_uv_p
            self.current_ma = 0
            self.test_running = False
            print("🛑 Simulator: BMS protection triggered (cell_uv_p)")

    def build_response(self, cmd_code, data):
        """Build BMS response frame"""
        length = len(data)
        checksum = (~(cmd_code + length + sum(data)) + 1) & 0xFFFF
        checksum_high = (checksum >> 8) & 0xFF
        checksum_low = checksum & 0xFF

        return bytes([
            self.START_BYTE,
            cmd_code,
            0x00,  # Status byte (placeholder)
            length,
            *data,
            checksum_high,
            checksum_low,
            self.STOP_BYTE
        ])

    def handle_cell_voltages_request(self):
        """Response to 0x04: Cell voltages"""
        data = []
        for v in self.cell_voltages:
            mv = int(v * 1000)
            data.append((mv >> 8) & 0xFF)
            data.append(mv & 0xFF)
        return self.build_response(self.CMD_CELL_VOLTAGES, data)

    def handle_basic_info_request(self):
        """Response to 0x03: Basic info"""
        total_v = int(sum(self.cell_voltages) * 100)  # 0.01V units
        current = int(self.current_ma / 10)  # 10mA units, signed
        residual = int(self.residual_capacity_mah / 10)  # 10mAh units
        nominal = int(self.nominal_capacity_mah / 10)

        data = [
            (total_v >> 8) & 0xFF, total_v & 0xFF,  # Total voltage
            (current >> 8) & 0xFF, current & 0xFF,  # Current (signed)
            (residual >> 8) & 0xFF, residual & 0xFF,  # Residual capacity
            (nominal >> 8) & 0xFF, nominal & 0xFF,  # Nominal capacity
            (self.cycle_count >> 8) & 0xFF, self.cycle_count & 0xFF,  # Cycle count
            0x00, 0x00,  # Production date (unused)
            0x00, 0x00,  # Balance status (unused)
            0x00, 0x00,  # Balance status high (unused)
            (self.protection_status >> 8) & 0xFF, self.protection_status & 0xFF,  # Protection
            0x10,  # Software version
            self.soc,  # SoC %
            0x03,  # FET status (both on)
            self.num_cells,  # Cell count
            len(self.temperatures),  # NTC count
        ]

        # Add temperatures (0.1K units, offset by 2731.5 for °C)
        for temp_c in self.temperatures:
            temp_k = int((temp_c + 273.15) * 10)
            data.append((temp_k >> 8) & 0xFF)
            data.append(temp_k & 0xFF)

        return self.build_response(self.CMD_BASIC_INFO, data)


def run_simulator_server(port='COM9', baud=9600):
    """
    Run BMS simulator on specified port.

    For Windows: Use virtual serial port software like com0com
    For Linux/Mac: Use socat to create virtual serial port pair

    Linux example:
        socat -d -d pty,raw,echo=0 pty,raw,echo=0
        # This creates two linked ports like /dev/pts/3 and /dev/pts/4
        # Connect app to one, run simulator on the other
    """
    print(f"🔌 BMS Simulator starting on {port} @ {baud} baud")
    print(f"   Connect Battery Test System to this port")
    print(f"   Test will auto-start when connected and complete in ~30 seconds\n")

    sim = AWarriorBMSSimulator()

    try:
        ser = serial.Serial(port, baud, timeout=1)
        print(f"✓ Listening on {port}")

        # Auto-start discharge after 2 seconds
        def auto_start():
            time.sleep(2)
            sim.start_discharge()

        threading.Thread(target=auto_start, daemon=True).start()

        while True:
            # Update simulation state
            sim.update_state()

            # Check for incoming requests
            if ser.in_waiting > 0:
                request = ser.read(ser.in_waiting)

                if len(request) < 4:
                    continue

                cmd = request[1] if len(request) > 1 else 0

                if cmd == sim.CMD_CELL_VOLTAGES:
                    response = sim.handle_cell_voltages_request()
                    ser.write(response)
                    print(f"→ Cell voltages: avg {sum(sim.cell_voltages) / len(sim.cell_voltages):.3f}V")

                elif cmd == sim.CMD_BASIC_INFO:
                    response = sim.handle_basic_info_request()
                    ser.write(response)
                    print(f"→ Basic info: {sim.current_ma / 1000:.1f}A, {sim.soc}%, "
                          f"{sim.residual_capacity_mah}mAh, Prot:0x{sim.protection_status:04X}")

            time.sleep(0.1)

    except serial.SerialException as e:
        print(f"❌ Serial error: {e}")
        print(f"\nTo create virtual serial ports:")
        print(f"  Windows: Install com0com (https://sourceforge.net/projects/com0com/)")
        print(f"  Linux/Mac: socat -d -d pty,raw,echo=0 pty,raw,echo=0")
    except KeyboardInterrupt:
        print("\n🛑 Simulator stopped")


if __name__ == '__main__':
    import sys

    print("=" * 60)
    print("BMS SIMULATOR - Battery Test System")
    print("=" * 60)

    # Try to auto-detect or prompt for port
    ports = list(serial.tools.list_ports.comports())

    if len(sys.argv) > 1:
        port = sys.argv[1]
    elif ports:
        print("\nAvailable ports:")
        for i, p in enumerate(ports):
            print(f"  {i + 1}. {p.device} - {p.description}")

        choice = input(f"\nSelect port (1-{len(ports)}) or enter custom: ")
        try:
            port = ports[int(choice) - 1].device
        except:
            port = choice
    else:
        port = input("Enter COM port (e.g., COM9 or /dev/pts/3): ")

    run_simulator_server(port)