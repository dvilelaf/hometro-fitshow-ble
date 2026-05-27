from __future__ import annotations

import asyncio
import contextlib
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from bleak import BleakClient

from .fitshow_oem import FITSHOW_NOTIFY_UUID, parse_fitshow_frame
from .ftms import (
    FITNESS_MACHINE_CONTROL_POINT_UUID,
    FITNESS_MACHINE_STATUS_UUID,
    TREADMILL_DATA_UUID,
    parse_control_point_response,
    parse_treadmill_data,
    pause_command,
    request_control_command,
    set_target_speed_command,
    start_or_resume_command,
    stop_command,
)
from .models import utc_now
from .protocol import hex_from_bytes
from .system_ble import is_system_connected, release_system_connection

DEFAULT_MIN_SPEED_KMH = 1.0
DEFAULT_MAX_SPEED_KMH = 14.0


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
    supported: dict[str, Any] = field(
        default_factory=lambda: {
            "min_speed_kmh": DEFAULT_MIN_SPEED_KMH,
            "max_speed_kmh": DEFAULT_MAX_SPEED_KMH,
            "speed_step_kmh": 0.1,
            "incline": False,
        }
    )

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


class TreadmillController:
    def __init__(self, address: str, *, timeout: float = 15.0) -> None:
        self.address = address
        self.timeout = timeout
        self.state = TreadmillState(address=address)
        self._client: BleakClient | None = None
        self._notify_chars: list[str] = []
        self._lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    @property
    def connected(self) -> bool:
        return bool(self._client and self._client.is_connected)

    async def connect(self) -> dict[str, Any]:
        async with self._lock:
            if self.connected:
                return self.state.snapshot()

            self._set_connection_state(ConnectionState.CONNECTING)
            self.state.last_error = None
            self.state.last_event_ts = utc_now()
            await self._publish()

            if await is_system_connected(self.address):
                await release_system_connection(self.address)
                await asyncio.sleep(0.5)

            for attempt in range(2):
                try:
                    await self._connect_once_unlocked()
                except Exception as retry_exc:
                    await self._disconnect_client_unlocked()
                    if attempt == 0:
                        await release_system_connection(self.address)
                        await asyncio.sleep(0.75)
                        continue
                    await self._handle_connect_failure_unlocked(retry_exc)
                    raise
                else:
                    self._set_connection_state(ConnectionState.CONNECTED)
                    break

            await self._publish()
            return self.state.snapshot()

    async def disconnect(self, *, stop_first: bool = True) -> dict[str, Any]:
        async with self._operation_lock:
            return await self._disconnect(stop_first=stop_first)

    async def _disconnect(self, *, stop_first: bool) -> dict[str, Any]:
        async with self._lock:
            self._set_connection_state(ConnectionState.DISCONNECTING)
            self.state.last_event_ts = utc_now()
            await self._publish()

            if self.connected and stop_first:
                with contextlib.suppress(Exception):
                    await self._send_control_unlocked(stop_command())
                    await asyncio.sleep(0.25)

            await self._disconnect_client_unlocked()
            self._set_connection_state(ConnectionState.DISCONNECTED)
            self._set_machine_state(MachineState.UNKNOWN)
            self.state.controlled = False
            self.state.last_event_ts = utc_now()
            await self._publish()
            return self.state.snapshot()

    async def _disconnect_client_unlocked(self) -> None:
        if not self._client:
            self._notify_chars.clear()
            return

        for char_uuid in list(self._notify_chars):
            with contextlib.suppress(Exception):
                await self._client.stop_notify(char_uuid)
        self._notify_chars.clear()

        with contextlib.suppress(Exception):
            await self._client.disconnect()

        self._client = None

    async def _connect_once_unlocked(self) -> None:
        self._client = BleakClient(self.address, timeout=self.timeout)
        await self._client.connect()
        self.state.last_error = None
        self.state.last_event_ts = utc_now()

        notify_chars = [
            FITNESS_MACHINE_CONTROL_POINT_UUID,
            FITNESS_MACHINE_STATUS_UUID,
            TREADMILL_DATA_UUID,
            FITSHOW_NOTIFY_UUID,
        ]
        for char_uuid in notify_chars:
            with contextlib.suppress(Exception):
                await self._client.start_notify(char_uuid, self._handle_notification)
                self._notify_chars.append(char_uuid)

    async def _handle_connect_failure_unlocked(self, exc: Exception) -> None:
        self._set_connection_state(ConnectionState.ERROR)
        self.state.controlled = False
        self.state.last_error = str(exc)
        self.state.last_event_ts = utc_now()
        await self._disconnect_client_unlocked()
        await self._publish()

    async def request_control(self) -> dict[str, Any]:
        await self._send_control(request_control_command())
        self.state.controlled = True
        await self._publish()
        return self.state.snapshot()

    async def start(self, speed_kmh: float | None = None) -> dict[str, Any]:
        return await self.play(speed_kmh)

    async def play(self, speed_kmh: float | None = None) -> dict[str, Any]:
        async with self._operation_lock:
            return await self._play_unlocked(speed_kmh)

    async def stop(self) -> dict[str, Any]:
        async with self._operation_lock:
            await self._send_control(stop_command())
            self._set_machine_state(MachineState.IDLE)
            await self._publish()
            return self.state.snapshot()

    async def pause(self) -> dict[str, Any]:
        async with self._operation_lock:
            return await self._pause_unlocked()

    async def pause_toggle(self) -> dict[str, Any]:
        async with self._operation_lock:
            if self.state.machine_state in {MachineState.RUNNING, MachineState.STARTING}:
                return await self._pause_unlocked()
            return await self._play_unlocked()

    async def resume(self) -> dict[str, Any]:
        return await self.play()

    async def set_speed(self, speed_kmh: float) -> dict[str, Any]:
        async with self._operation_lock:
            speed_kmh = self._validate_speed(speed_kmh)
            self.state.target_speed_kmh = speed_kmh

            if self.state.machine_state in {MachineState.RUNNING, MachineState.STARTING}:
                await self.request_control()
                await self._send_control(set_target_speed_command(speed_kmh))

            await self._publish()
            return self.state.snapshot()

    async def _play_unlocked(self, speed_kmh: float | None = None) -> dict[str, Any]:
        if speed_kmh is not None:
            self.state.target_speed_kmh = self._validate_speed(speed_kmh)
        await self.connect()
        await self.request_control()
        await self._send_control(set_target_speed_command(self.state.target_speed_kmh))
        await self._send_control(start_or_resume_command())
        self._set_machine_state(MachineState.STARTING)
        await self._publish()
        return self.state.snapshot()

    async def _pause_unlocked(self) -> dict[str, Any]:
        await self._send_control(pause_command())
        self._set_machine_state(MachineState.PAUSED)
        await self._publish()
        return self.state.snapshot()

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=20)
        self._subscribers.add(queue)
        await queue.put(self.state.snapshot())
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    async def _send_control(self, payload: bytes) -> None:
        await self.connect()
        async with self._lock:
            await self._send_control_unlocked(payload)

    async def _send_control_unlocked(self, payload: bytes) -> None:
        if not self._client or not self._client.is_connected:
            message = "treadmill is not connected"
            self._set_connection_state(ConnectionState.ERROR)
            self.state.last_error = message
            self.state.last_event_ts = utc_now()
            await self._publish()
            raise RuntimeError(message)
        await self._client.write_gatt_char(
            FITNESS_MACHINE_CONTROL_POINT_UUID,
            payload,
            response=True,
        )
        self.state.last_raw_hex = hex_from_bytes(payload)
        self.state.last_event_ts = utc_now()

    def _handle_notification(self, sender: Any, data: bytearray) -> None:
        sender_uuid = getattr(sender, "uuid", str(sender))
        raw = bytes(data)
        self.state.last_event_ts = utc_now()
        self.state.last_raw_hex = hex_from_bytes(raw)

        if sender_uuid == FITNESS_MACHINE_CONTROL_POINT_UUID:
            response = parse_control_point_response(raw)
            if response:
                self.state.last_response = f"{response.request_name}:{response.result_name}"
        elif sender_uuid == FITNESS_MACHINE_STATUS_UUID:
            self.state.ftms_status_hex = hex_from_bytes(raw)
            if raw.startswith(b"\x02"):
                self._set_machine_state(MachineState.IDLE)
        elif sender_uuid == TREADMILL_DATA_UUID:
            treadmill_data = parse_treadmill_data(raw)
            if treadmill_data:
                if treadmill_data.instantaneous_speed_kmh is not None:
                    self.state.speed_kmh = treadmill_data.instantaneous_speed_kmh
                    if treadmill_data.instantaneous_speed_kmh > 0:
                        self._set_machine_state(MachineState.RUNNING)
                if treadmill_data.total_distance_m is not None:
                    self.state.distance_m = treadmill_data.total_distance_m
                if treadmill_data.total_energy_kcal is not None:
                    self.state.calories_kcal = treadmill_data.total_energy_kcal
                if treadmill_data.elapsed_time_s is not None:
                    self.state.elapsed_s = treadmill_data.elapsed_time_s
        elif sender_uuid == FITSHOW_NOTIFY_UUID:
            frame = parse_fitshow_frame(raw)
            if frame:
                self.state.fitshow_state = frame.state_name
                self._apply_fitshow_machine_state(frame.state_name)
                if frame.speed_kmh is not None:
                    self.state.speed_kmh = frame.speed_kmh
                if frame.distance_m is not None:
                    self.state.distance_m = frame.distance_m
                if frame.elapsed_s is not None:
                    self.state.elapsed_s = frame.elapsed_s

        asyncio.create_task(self._publish())

    def _set_connection_state(self, state: ConnectionState) -> None:
        self.state.connection_state = state
        self.state.connected = state == ConnectionState.CONNECTED

    def _set_machine_state(self, state: MachineState) -> None:
        self.state.machine_state = state
        self.state.running = state in {MachineState.STARTING, MachineState.RUNNING}
        self.state.paused = state == MachineState.PAUSED

    def _apply_fitshow_machine_state(self, state_name: str) -> None:
        state_map = {
            "idle": MachineState.IDLE,
            "countdown": MachineState.STARTING,
            "running": MachineState.RUNNING,
            "stopping": MachineState.STOPPING,
        }
        machine_state = state_map.get(state_name)
        if machine_state is not None:
            self._set_machine_state(machine_state)

    async def _publish(self) -> None:
        snapshot = self.state.snapshot()
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in self._subscribers:
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            try:
                queue.put_nowait(snapshot)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self._subscribers.discard(queue)

    def _validate_speed(self, speed_kmh: float) -> float:
        min_speed = float(self.state.supported["min_speed_kmh"])
        max_speed = float(self.state.supported["max_speed_kmh"])
        if not min_speed <= speed_kmh <= max_speed:
            raise ValueError(f"speed must be between {min_speed:.1f} and {max_speed:.1f} km/h")
        return round(speed_kmh, 1)
