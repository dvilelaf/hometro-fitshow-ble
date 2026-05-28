from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .fitshow_oem import FITSHOW_NOTIFY_UUID, FITSHOW_SERVICE_UUID, parse_fitshow_frame
from .ftms import (
    FITNESS_MACHINE_CONTROL_POINT_UUID,
    FITNESS_MACHINE_SERVICE_UUID,
    FITNESS_MACHINE_STATUS_UUID,
    TREADMILL_DATA_UUID,
    parse_control_point_response,
    parse_treadmill_data,
)
from .protocol import hex_from_bytes


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def bytes_map_to_json(data: dict[Any, bytes] | None) -> dict[str, str]:
    return {str(key): value.hex(" ") for key, value in (data or {}).items()}


def normalize_uuid(value: str) -> str:
    value = value.lower()
    if len(value) == 4:
        return f"0000{value}-0000-1000-8000-00805f9b34fb"
    return value


class ConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    ERROR = "error"


class MachineState(StrEnum):
    UNKNOWN = "unknown"
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"


DEFAULT_MIN_SPEED_KMH = 1.0
DEFAULT_MAX_SPEED_KMH = 14.0
SUPPORTED_DEFAULTS = {
    "min_speed_kmh": DEFAULT_MIN_SPEED_KMH,
    "max_speed_kmh": DEFAULT_MAX_SPEED_KMH,
    "speed_step_kmh": 0.1,
    "incline": False,
}


@dataclass
class TreadmillState:
    address: str
    connection_state: ConnectionState = ConnectionState.DISCONNECTED
    machine_state: MachineState = MachineState.UNKNOWN
    connected: bool = False
    controlled: bool = False
    running: bool = False
    paused: bool = False
    speed_kmh: float = 0.0
    target_speed_kmh: float = DEFAULT_MIN_SPEED_KMH
    distance_m: int = 0
    calories_kcal: int | None = None
    elapsed_s: int | None = None
    ftms_status_hex: str | None = None
    fitshow_state: str | None = None
    last_response: str | None = None
    last_error: str | None = None
    last_event_ts: str | None = None
    last_raw_hex: str | None = None
    supported: dict[str, Any] = field(default_factory=SUPPORTED_DEFAULTS.copy)

    def snapshot(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["primary_action"] = self.primary_action()
        payload["primary_action_label"] = self.primary_action_label()
        return payload

    def primary_action(self) -> str:
        if self.machine_state in {MachineState.RUNNING, MachineState.STARTING}:
            return "pause"
        if self.machine_state == MachineState.PAUSED:
            return "resume"
        return "start"

    def primary_action_label(self) -> str:
        return self.primary_action().title()

    def validate_speed(self, speed_kmh: float) -> float:
        min_speed = float(self.supported["min_speed_kmh"])
        max_speed = float(self.supported["max_speed_kmh"])
        if not min_speed <= speed_kmh <= max_speed:
            raise ValueError(f"speed must be between {min_speed:.1f} and {max_speed:.1f} km/h")
        return round(speed_kmh, 1)

    def set_connection(self, state: ConnectionState) -> None:
        self.connection_state = state
        self.connected = state == ConnectionState.CONNECTED

    def set_machine(self, state: MachineState) -> None:
        self.machine_state = state
        self.running = state in {MachineState.STARTING, MachineState.RUNNING}
        self.paused = state == MachineState.PAUSED

    def set_observed_machine(self, state: MachineState) -> None:
        if self.machine_state == MachineState.PAUSED:
            return
        self.set_machine(state)

    def reset_session_metrics(self) -> None:
        self.distance_m = 0
        self.calories_kcal = 0
        self.elapsed_s = 0

    def apply_distance(self, distance_m: int) -> None:
        if distance_m >= self.distance_m:
            self.distance_m = distance_m

    def apply_calories(self, calories_kcal: int) -> None:
        if self.calories_kcal is None or calories_kcal >= self.calories_kcal:
            self.calories_kcal = calories_kcal

    def apply_elapsed(self, elapsed_s: int) -> None:
        if self.elapsed_s is None or elapsed_s >= self.elapsed_s:
            self.elapsed_s = elapsed_s

    def apply_treadmill_data(self, data: Any) -> None:
        if data.instantaneous_speed_kmh is not None:
            self.speed_kmh = data.instantaneous_speed_kmh
            if data.instantaneous_speed_kmh > 0:
                self.set_observed_machine(MachineState.RUNNING)
        if data.total_distance_m is not None:
            self.apply_distance(data.total_distance_m)
        if data.total_energy_kcal is not None:
            self.apply_calories(data.total_energy_kcal)
        if data.elapsed_time_s is not None:
            self.apply_elapsed(data.elapsed_time_s)

    def apply_fitshow_frame(self, frame: Any) -> None:
        self.fitshow_state = frame.state_name
        if machine_state := FITSHOW_STATE_MAP.get(frame.state_name):
            self.set_observed_machine(machine_state)
        if frame.speed_kmh is not None:
            self.speed_kmh = frame.speed_kmh
        if frame.distance_m is not None:
            self.apply_distance(frame.distance_m)
        if frame.elapsed_s is not None:
            self.apply_elapsed(frame.elapsed_s)

    def apply_notification(self, sender_uuid: str, raw: bytes) -> None:
        self.last_event_ts = utc_now()
        self.last_raw_hex = hex_from_bytes(raw)

        if sender_uuid == FITNESS_MACHINE_CONTROL_POINT_UUID:
            if response := parse_control_point_response(raw):
                self.last_response = f"{response.request_name}:{response.result_name}"
        elif sender_uuid == FITNESS_MACHINE_STATUS_UUID:
            self.ftms_status_hex = hex_from_bytes(raw)
            if raw.startswith(b"\x02"):
                self.set_observed_machine(MachineState.IDLE)
        elif sender_uuid == TREADMILL_DATA_UUID:
            if treadmill_data := parse_treadmill_data(raw):
                self.apply_treadmill_data(treadmill_data)
        elif sender_uuid == FITSHOW_NOTIFY_UUID:
            if frame := parse_fitshow_frame(raw):
                self.apply_fitshow_frame(frame)


FITSHOW_STATE_MAP = {
    "idle": MachineState.IDLE,
    "countdown": MachineState.STARTING,
    "running": MachineState.RUNNING,
    "stopping": MachineState.STOPPING,
}


@dataclass(frozen=True)
class AdvertisementRecord:
    address: str | None
    name: str | None
    details: str
    rssi: int | None
    local_name: str | None
    manufacturer_data: dict[str, str]
    service_data: dict[str, str]
    service_uuids: list[str]
    tx_power: int | None

    @classmethod
    def from_bleak(cls, device: Any, advertisement: Any) -> AdvertisementRecord:
        return cls(
            address=getattr(device, "address", None),
            name=getattr(device, "name", None),
            details=str(getattr(device, "details", "")),
            rssi=getattr(advertisement, "rssi", getattr(device, "rssi", None)),
            local_name=getattr(advertisement, "local_name", None),
            manufacturer_data=bytes_map_to_json(
                getattr(advertisement, "manufacturer_data", None)
            ),
            service_data=bytes_map_to_json(getattr(advertisement, "service_data", None)),
            service_uuids=list(getattr(advertisement, "service_uuids", []) or []),
            tx_power=getattr(advertisement, "tx_power", None),
        )

    def matches(self, needle: str | None) -> bool:
        if not needle:
            return True
        haystack = " ".join(
            str(value or "")
            for value in (self.name, self.local_name, self.address, self.service_uuids)
        ).lower()
        return needle.lower() in haystack

    def is_known_treadmill(self) -> bool:
        services = {normalize_uuid(uuid) for uuid in self.service_uuids}
        names = f"{self.name or ''} {self.local_name or ''}".lower()
        known_name = any(marker in names for marker in ("fs-", "fitshow", "hometro"))
        known_service = bool(services & {FITNESS_MACHINE_SERVICE_UUID, FITSHOW_SERVICE_UUID})
        return known_name and known_service

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DescriptorRecord:
    uuid: str
    handle: int | None
    description: str | None


@dataclass(frozen=True)
class CharacteristicRecord:
    uuid: str
    description: str | None
    handle: int | None
    properties: list[str]
    descriptors: list[DescriptorRecord] = field(default_factory=list)


@dataclass(frozen=True)
class ServiceRecord:
    uuid: str
    description: str | None
    handle: int | None
    characteristics: list[CharacteristicRecord] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NotificationEvent:
    ts: str
    address: str
    char: str
    hex: str
    length: int
    decoded: dict[str, Any] | None = None
    type: str = "notify"

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["len"] = payload.pop("length")
        if payload["decoded"] is None:
            payload.pop("decoded")
        return payload


@dataclass(frozen=True)
class WriteEvent:
    ts: str
    address: str
    char: str
    hex: str
    response: bool
    type: str = "write"
    index: int | None = None

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["index"] is None:
            payload.pop("index")
        return payload
