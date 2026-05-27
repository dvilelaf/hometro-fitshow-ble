from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

FITNESS_MACHINE_SERVICE_UUID = "00001826-0000-1000-8000-00805f9b34fb"
FITNESS_MACHINE_CONTROL_POINT_UUID = "00002ad9-0000-1000-8000-00805f9b34fb"
FITNESS_MACHINE_STATUS_UUID = "00002ada-0000-1000-8000-00805f9b34fb"
TREADMILL_DATA_UUID = "00002acd-0000-1000-8000-00805f9b34fb"


class ControlPointOpCode(IntEnum):
    REQUEST_CONTROL = 0x00
    RESET = 0x01
    SET_TARGET_SPEED = 0x02
    SET_TARGET_INCLINATION = 0x03
    SET_TARGET_RESISTANCE_LEVEL = 0x04
    SET_TARGET_POWER = 0x05
    SET_TARGET_HEART_RATE = 0x06
    START_OR_RESUME = 0x07
    STOP_OR_PAUSE = 0x08
    RESPONSE_CODE = 0x80


class StopPauseCode(IntEnum):
    STOP = 0x01
    PAUSE = 0x02


class ControlPointResultCode(IntEnum):
    SUCCESS = 0x01
    NOT_SUPPORTED = 0x02
    INCORRECT_PARAMETER = 0x03
    OPERATION_FAILED = 0x04
    CONTROL_NOT_PERMITTED = 0x05


@dataclass(frozen=True)
class TreadmillData:
    flags: int
    instantaneous_speed_kmh: float | None = None
    average_speed_kmh: float | None = None
    total_distance_m: int | None = None
    total_energy_kcal: int | None = None
    elapsed_time_s: int | None = None
    remaining_time_s: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "type": "ftms_treadmill_data",
                "flags": self.flags,
                "instantaneous_speed_kmh": self.instantaneous_speed_kmh,
                "average_speed_kmh": self.average_speed_kmh,
                "total_distance_m": self.total_distance_m,
                "total_energy_kcal": self.total_energy_kcal,
                "elapsed_time_s": self.elapsed_time_s,
                "remaining_time_s": self.remaining_time_s,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class ControlPointResponse:
    request_code: int
    result_code: int

    @property
    def request_name(self) -> str:
        return _enum_name(ControlPointOpCode, self.request_code)

    @property
    def result_name(self) -> str:
        return _enum_name(ControlPointResultCode, self.result_code)


def _enum_name(enum_type: type[IntEnum], value: int) -> str:
    try:
        return enum_type(value).name.lower()
    except ValueError:
        return f"unknown_0x{value:02x}"


def request_control_command() -> bytes:
    return bytes([ControlPointOpCode.REQUEST_CONTROL])


def start_or_resume_command() -> bytes:
    return bytes([ControlPointOpCode.START_OR_RESUME])


def stop_command() -> bytes:
    return bytes([ControlPointOpCode.STOP_OR_PAUSE, StopPauseCode.STOP])


def pause_command() -> bytes:
    return bytes([ControlPointOpCode.STOP_OR_PAUSE, StopPauseCode.PAUSE])


def set_target_speed_command(speed_kmh: float) -> bytes:
    if speed_kmh < 0:
        raise ValueError("speed_kmh must be positive")
    speed_raw = round(speed_kmh * 100)
    if speed_raw > 0xFFFF:
        raise ValueError("speed_kmh is too large for FTMS uint16 target speed")
    return bytes([ControlPointOpCode.SET_TARGET_SPEED]) + speed_raw.to_bytes(2, "little")


def parse_control_point_response(data: bytes) -> ControlPointResponse | None:
    if len(data) < 3 or data[0] != ControlPointOpCode.RESPONSE_CODE:
        return None
    return ControlPointResponse(request_code=data[1], result_code=data[2])


def parse_treadmill_data(data: bytes) -> TreadmillData | None:
    if len(data) < 2:
        return None

    flags = int.from_bytes(data[:2], "little")
    offset = 2

    def read_uint16() -> int | None:
        nonlocal offset
        if offset + 2 > len(data):
            return None
        value = int.from_bytes(data[offset : offset + 2], "little")
        offset += 2
        return value

    def read_uint24() -> int | None:
        nonlocal offset
        if offset + 3 > len(data):
            return None
        value = int.from_bytes(data[offset : offset + 3], "little")
        offset += 3
        return value

    def skip(size: int) -> bool:
        nonlocal offset
        if offset + size > len(data):
            return False
        offset += size
        return True

    instantaneous_speed = None
    if not flags & 0x0001:
        raw_speed = read_uint16()
        if raw_speed is not None:
            instantaneous_speed = raw_speed / 100

    average_speed = None
    if flags & 0x0002:
        raw_average_speed = read_uint16()
        if raw_average_speed is not None:
            average_speed = raw_average_speed / 100

    total_distance = read_uint24() if flags & 0x0004 else None

    if flags & 0x0008:
        skip(4)  # inclination + ramp angle setting
    if flags & 0x0010:
        skip(4)  # positive + negative elevation gain
    if flags & 0x0020:
        skip(1)  # instantaneous pace
    if flags & 0x0040:
        skip(1)  # average pace
    total_energy = None
    if flags & 0x0080:
        raw_total_energy = read_uint16()
        if raw_total_energy is not None and raw_total_energy != 0xFFFF:
            total_energy = raw_total_energy
        skip(3)  # energy/hour + energy/minute
    if flags & 0x0100:
        skip(1)  # heart rate
    if flags & 0x0200:
        skip(1)  # metabolic equivalent

    elapsed_time = read_uint16() if flags & 0x0400 else None
    remaining_time = read_uint16() if flags & 0x0800 else None

    if flags & 0x1000:
        skip(2)  # force on belt
    if flags & 0x2000:
        skip(2)  # power output

    return TreadmillData(
        flags=flags,
        instantaneous_speed_kmh=instantaneous_speed,
        average_speed_kmh=average_speed,
        total_distance_m=total_distance,
        total_energy_kcal=total_energy,
        elapsed_time_s=elapsed_time,
        remaining_time_s=remaining_time,
    )
