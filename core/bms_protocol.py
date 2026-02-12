"""
A-Warrior BMS Protocol Handler
General Protocol V4 - RS485/RS232/UART
Shared between Desktop and Web apps
"""

import struct


class AWarriorBMS:
    """A-Warrior BMS Protocol Implementation"""

    START_BYTE       = 0xDD
    STOP_BYTE        = 0x77
    STATUS_READ      = 0xA5
    STATUS_WRITE     = 0x5A
    CMD_BASIC_INFO   = 0x03
    CMD_CELL_VOLTAGES = 0x04
    CMD_VERSION      = 0x05
    CMD_MOS_CONTROL  = 0xE1

    # ── Frame Building ────────────────────────────────────────────────────────

    @staticmethod
    def calculate_checksum(data):
        """Checksum = ~(sum of bytes) + 1, returned as (high, low)"""
        checksum = (~sum(data) + 1) & 0xFFFF
        return (checksum >> 8) & 0xFF, checksum & 0xFF

    @staticmethod
    def build_request_frame(command_code, data_content=None):
        """Build a complete request frame"""
        if data_content is None:
            data_content = []
        length = len(data_content)
        checksum_high, checksum_low = AWarriorBMS.calculate_checksum(
            [command_code, length] + list(data_content)
        )
        return bytes([
            AWarriorBMS.START_BYTE,
            AWarriorBMS.STATUS_READ,
            command_code,
            length,
            *data_content,
            checksum_high,
            checksum_low,
            AWarriorBMS.STOP_BYTE
        ])

    # ── Frame Validation ──────────────────────────────────────────────────────

    @staticmethod
    def validate_response(response):
        """
        Validate response frame.
        Response format: START(1) + CMD(1) + ??(1) + LEN(1) + DATA(LEN) + CK(2) + STOP(1)
        """
        if len(response) < 7:
            return False
        if response[0] != AWarriorBMS.START_BYTE:
            return False
        if response[-1] != AWarriorBMS.STOP_BYTE:
            return False

        length = response[3]
        expected = 1 + 1 + 1 + 1 + length + 2 + 1   # 7 + length
        if len(response) != expected:
            return False

        return True

    # ── Parsers ───────────────────────────────────────────────────────────────

    @staticmethod
    def parse_cell_voltages(response):
        """
        Parse command 0x04 response.
        Returns list of all voltages in Volts (including dead/bad cells).
        """
        if not AWarriorBMS.validate_response(response):
            return None

        data = response[4:-3]
        voltages = []
        for i in range(0, len(data) - 1, 2):
            mv = struct.unpack('>H', data[i:i+2])[0]
            voltages.append(round(mv / 1000.0, 3))
        return voltages

    @staticmethod
    def parse_basic_info(response):
        """
        Parse command 0x03 response.
        Returns dict with capacity, current, SoC, temperature, etc.
        """
        if not AWarriorBMS.validate_response(response):
            return None

        data = response[4:-3]
        if len(data) < 23:
            return None

        try:
            total_voltage      = struct.unpack('>H', data[0:2])[0] * 10   # mV
            current            = struct.unpack('>h', data[2:4])[0] * 10   # mA signed
            residual_capacity  = struct.unpack('>H', data[4:6])[0] * 10   # mAh
            nominal_capacity   = struct.unpack('>H', data[6:8])[0] * 10   # mAh
            cycle_life         = struct.unpack('>H', data[8:10])[0]
            protection_status  = struct.unpack('>H', data[16:18])[0]
            software_version   = data[18]
            rsoc               = data[19]
            fet_status         = data[20]
            cell_count         = data[21]
            ntc_count          = data[22]

            temperatures = []
            offset = 23
            for _ in range(ntc_count):
                if offset + 2 <= len(data):
                    raw = struct.unpack('>H', data[offset:offset+2])[0]
                    temperatures.append(round((raw * 0.1) - 273.15, 1))
                    offset += 2

            return {
                'total_voltage_mv':       total_voltage,
                'current_ma':             current,
                'residual_capacity_mah':  residual_capacity,
                'nominal_capacity_mah':   nominal_capacity,
                'cycle_life':             cycle_life,
                'protection_status':      protection_status,
                'software_version':       software_version,
                'rsoc_percent':           rsoc,
                'fet_status':             fet_status,
                'cell_count':             cell_count,
                'ntc_count':              ntc_count,
                'temperatures_c':         temperatures,
            }
        except Exception as e:
            print(f"  Basic info parse error: {e}")
            return None

    # ── Convenience Requests ──────────────────────────────────────────────────

    @staticmethod
    def get_basic_info_request():
        return AWarriorBMS.build_request_frame(AWarriorBMS.CMD_BASIC_INFO)

    @staticmethod
    def get_cell_voltages_request():
        return AWarriorBMS.build_request_frame(AWarriorBMS.CMD_CELL_VOLTAGES)

    @staticmethod
    def get_version_request():
        return AWarriorBMS.build_request_frame(AWarriorBMS.CMD_VERSION)
