"""
A-Warrior BMS Protocol Handler
General Protocol V4 - RS485/RS232/UART.

This version keeps the original protocol layout while allowing partial Basic
Information payloads. Older or variant BMS firmware can therefore provide the
fields it supports without the entire response being discarded.
"""

from __future__ import annotations

import struct
from typing import Any


class AWarriorBMS:
    """A-Warrior/JBD-style BMS protocol implementation."""

    START_BYTE = 0xDD
    STOP_BYTE = 0x77

    STATUS_READ = 0xA5
    STATUS_WRITE = 0x5A

    CMD_BASIC_INFO = 0x03
    CMD_CELL_VOLTAGES = 0x04
    CMD_VERSION = 0x05
    CMD_MOS_CONTROL = 0xE1

    @staticmethod
    def calculate_checksum(data: list[int] | bytes | bytearray) -> tuple[int, int]:
        """Return the protocol's two-byte one's-complement checksum."""
        checksum = (~sum(data) + 1) & 0xFFFF
        return (checksum >> 8) & 0xFF, checksum & 0xFF

    @staticmethod
    def build_request_frame(
        command_code: int,
        data_content: list[int] | bytes | bytearray | None = None,
    ) -> bytes:
        """Build a read-request frame for the supplied command."""
        if data_content is None:
            data_content = []

        payload = list(data_content)
        length = len(payload)
        checksum_high, checksum_low = AWarriorBMS.calculate_checksum(
            [command_code, length] + payload
        )

        return bytes(
            [
                AWarriorBMS.START_BYTE,
                AWarriorBMS.STATUS_READ,
                command_code,
                length,
                *payload,
                checksum_high,
                checksum_low,
                AWarriorBMS.STOP_BYTE,
            ]
        )

    @staticmethod
    def validate_response(response: bytes) -> bool:
        """Validate the frame envelope and declared payload length.

        The recovered application did not validate response checksums, so that
        behavior is retained to avoid rejecting BMS variants that calculate or
        report checksums differently.
        """
        if len(response) < 7:
            return False
        if response[0] != AWarriorBMS.START_BYTE:
            return False
        if response[-1] != AWarriorBMS.STOP_BYTE:
            return False

        payload_length = response[3]
        expected_length = 4 + payload_length + 2 + 1
        return len(response) == expected_length

    @staticmethod
    def _payload(response: bytes) -> bytes | None:
        """Return the declared response payload after validating the frame."""
        if not AWarriorBMS.validate_response(response):
            return None

        payload_length = response[3]
        return response[4 : 4 + payload_length]

    @staticmethod
    def parse_cell_voltages(response: bytes) -> list[float] | None:
        """Parse command 0x04 cell voltages into volts."""
        data = AWarriorBMS._payload(response)
        if data is None:
            return None

        voltages: list[float] = []
        for offset in range(0, len(data) - 1, 2):
            millivolts = struct.unpack(">H", data[offset : offset + 2])[0]
            voltages.append(round(millivolts / 1000.0, 3))

        return voltages

    @staticmethod
    def parse_basic_info(response: bytes) -> dict[str, Any] | None:
        """Parse all Basic Information fields available in the payload.

        Standard firmware supplies at least 23 bytes before the NTC values.
        Some compatible BMS revisions return a shorter payload. The original
        parser rejected those frames entirely, which hid current, SOC and
        capacity even when their bytes were present. This parser adds each
        field only when its required bytes exist.
        """
        data = AWarriorBMS._payload(response)
        if data is None:
            return None

        if len(data) < 2:
            print(
                "⚠ Basic info payload is too short: "
                f"{len(data)} byte(s), payload={data.hex(' ')}"
            )
            return None

        info: dict[str, Any] = {
            "payload_length": len(data),
            "raw_payload_hex": data.hex(" "),
            "temperatures_c": [],
        }

        try:
            if len(data) >= 2:
                info["total_voltage_mv"] = (
                    struct.unpack(">H", data[0:2])[0] * 10
                )

            if len(data) >= 4:
                # Signed 16-bit value. Negative means discharging.
                info["current_ma"] = struct.unpack(">h", data[2:4])[0] * 10

            if len(data) >= 6:
                info["residual_capacity_mah"] = (
                    struct.unpack(">H", data[4:6])[0] * 10
                )

            if len(data) >= 8:
                info["nominal_capacity_mah"] = (
                    struct.unpack(">H", data[6:8])[0] * 10
                )

            if len(data) >= 10:
                info["cycle_life"] = struct.unpack(">H", data[8:10])[0]

            # Bytes 10-15 contain production date and balance status in the
            # standard protocol. The recovered app did not use those fields.
            if len(data) >= 18:
                info["protection_status"] = struct.unpack(">H", data[16:18])[0]

            if len(data) >= 19:
                info["software_version"] = data[18]

            if len(data) >= 20:
                info["rsoc_percent"] = data[19]

            if len(data) >= 21:
                info["fet_status"] = data[20]

            if len(data) >= 22:
                info["cell_count"] = data[21]

            if len(data) >= 23:
                ntc_count = data[22]
                info["ntc_count"] = ntc_count

                temperatures: list[float] = []
                offset = 23
                for _ in range(ntc_count):
                    if offset + 2 > len(data):
                        break
                    raw_temperature = struct.unpack(">H", data[offset : offset + 2])[0]
                    temperatures.append(round(raw_temperature * 0.1 - 273.15, 1))
                    offset += 2

                info["temperatures_c"] = temperatures

            return info

        except (IndexError, struct.error, TypeError, ValueError) as error:
            print(
                "⚠ Basic info parse error: "
                f"{error}; payload_length={len(data)}; "
                f"payload={data.hex(' ')}"
            )
            return None

    @staticmethod
    def get_basic_info_request() -> bytes:
        return AWarriorBMS.build_request_frame(AWarriorBMS.CMD_BASIC_INFO)

    @staticmethod
    def get_cell_voltages_request() -> bytes:
        return AWarriorBMS.build_request_frame(AWarriorBMS.CMD_CELL_VOLTAGES)

    @staticmethod
    def get_version_request() -> bytes:
        return AWarriorBMS.build_request_frame(AWarriorBMS.CMD_VERSION)