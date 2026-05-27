from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

FITSHOW_NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
FITSHOW_WRITE_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"

STX = 0x02
ETX = 0x03


class FitShowState(IntEnum):
    IDLE = 0x00
    COUNTDOWN = 0x02
    RUNNING = 0x03
    STOPPING = 0x04


@dataclass(frozen=True)
class FitShowFrame:
    command: int
    state: int
    checksum_ok: bool
    speed_kmh: float | None = None
    countdown_s: int | None = None
    elapsed_s: int | None = None
    distance_m: int | None = None
    raw_fields: list[int] | None = None

    @property
    def state_name(self) -> str:
        try:
            return FitShowState(self.state).name.lower()
        except ValueError:
            return f"unknown_0x{self.state:02x}"

    def to_json(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "type": "fitshow_oem",
                "command": self.command,
                "state": self.state_name,
                "checksum_ok": self.checksum_ok,
                "speed_kmh": self.speed_kmh,
                "countdown_s": self.countdown_s,
                "elapsed_s": self.elapsed_s,
                "distance_m": self.distance_m,
                "raw_fields": self.raw_fields,
            }.items()
            if value is not None
        }


def xor_checksum(data: bytes) -> int:
    checksum = 0
    for value in data:
        checksum ^= value
    return checksum


def parse_fitshow_frame(data: bytes) -> FitShowFrame | None:
    if len(data) < 5 or data[0] != STX or data[-1] != ETX:
        return None

    body = data[1:-2]
    checksum = data[-2]
    checksum_ok = xor_checksum(body) == checksum
    if len(body) < 2:
        return None

    command = body[0]
    state = body[1]
    payload = body[2:]
    speed_kmh = None
    countdown_s = None
    elapsed_s = None
    distance_m = None
    raw_fields = None

    if state == FitShowState.COUNTDOWN and payload:
        countdown_s = payload[0]

    if state in (FitShowState.RUNNING, FitShowState.STOPPING) and len(payload) >= 4:
        speed_kmh = int.from_bytes(payload[0:2], "little") / 10
        elapsed_s = int.from_bytes(payload[2:4], "little")
        if len(payload) >= 6:
            distance_m = int.from_bytes(payload[4:6], "little")
        if len(payload) > 6:
            raw_fields = [
                int.from_bytes(payload[index : index + 2], "little")
                for index in range(6, len(payload), 2)
                if index + 2 <= len(payload)
            ]

    return FitShowFrame(
        command=command,
        state=state,
        checksum_ok=checksum_ok,
        speed_kmh=speed_kmh,
        countdown_s=countdown_s,
        elapsed_s=elapsed_s,
        distance_m=distance_m,
        raw_fields=raw_fields,
    )
