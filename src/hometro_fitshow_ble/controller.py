from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from bleak import BleakClient

from .fitshow_oem import FITSHOW_NOTIFY_UUID
from .ftms import (
    FITNESS_MACHINE_CONTROL_POINT_UUID,
    FITNESS_MACHINE_STATUS_UUID,
    TREADMILL_DATA_UUID,
    pause_command,
    request_control_command,
    set_target_speed_command,
    start_or_resume_command,
    stop_command,
)
from .models import ConnectionState, MachineState, TreadmillState, utc_now
from .protocol import hex_from_bytes
from .system_ble import is_system_connected, release_system_connection

NOTIFY_UUIDS = (
    FITNESS_MACHINE_CONTROL_POINT_UUID,
    FITNESS_MACHINE_STATUS_UUID,
    TREADMILL_DATA_UUID,
    FITSHOW_NOTIFY_UUID,
)
TARGET_RESTORE_ATTEMPTS = 5
TARGET_RESTORE_INTERVAL_SECONDS = 0.75


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

            self.state.set_connection(ConnectionState.CONNECTING)
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
                    if attempt:
                        self.state.set_connection(ConnectionState.ERROR)
                        self.state.controlled = False
                        self.state.last_error = str(retry_exc)
                        self.state.last_event_ts = utc_now()
                        await self._publish()
                        raise
                    await release_system_connection(self.address)
                    await asyncio.sleep(0.75)
                    continue

                self.state.set_connection(ConnectionState.CONNECTED)
                break

            await self._publish()
            return self.state.snapshot()

    async def disconnect(self, *, stop_first: bool = True) -> dict[str, Any]:
        async with self._operation_lock, self._lock:
            self.state.set_connection(ConnectionState.DISCONNECTING)
            self.state.last_event_ts = utc_now()
            await self._publish()

            if self.connected and stop_first:
                with contextlib.suppress(Exception):
                    await self._send_control_unlocked(stop_command())
                    await asyncio.sleep(0.25)

            await self._disconnect_client_unlocked()
            self.state.set_connection(ConnectionState.DISCONNECTED)
            self.state.set_machine(MachineState.UNKNOWN)
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

        for char_uuid in NOTIFY_UUIDS:
            with contextlib.suppress(Exception):
                await self._client.start_notify(char_uuid, self._handle_notification)
                self._notify_chars.append(char_uuid)

    async def request_control(self) -> dict[str, Any]:
        await self._send_control(request_control_command())
        self.state.controlled = True
        await self._publish()
        return self.state.snapshot()

    async def connection_toggle(self) -> dict[str, Any]:
        if self.connected:
            return await self.disconnect(stop_first=True)
        return await self.connect()

    async def play(self, speed_kmh: float | None = None) -> dict[str, Any]:
        async with self._operation_lock:
            return await self._play_unlocked(speed_kmh)

    async def primary_action(self) -> dict[str, Any]:
        async with self._operation_lock:
            if self.state.machine_state in {MachineState.RUNNING, MachineState.STARTING}:
                return await self._send_and_set_state(pause_command(), MachineState.PAUSED)
            return await self._play_unlocked()

    async def stop(self) -> dict[str, Any]:
        async with self._operation_lock:
            return await self._send_and_set_state(stop_command(), MachineState.IDLE)

    async def pause_toggle(self) -> dict[str, Any]:
        return await self.primary_action()

    async def set_speed(self, speed_kmh: float) -> dict[str, Any]:
        async with self._operation_lock:
            speed_kmh = self.state.validate_speed(speed_kmh)
            self.state.target_speed_kmh = speed_kmh

            if self.state.machine_state in {MachineState.RUNNING, MachineState.STARTING}:
                await self.request_control()
                await self._send_control(set_target_speed_command(speed_kmh))

            await self._publish()
            return self.state.snapshot()

    async def _play_unlocked(self, speed_kmh: float | None = None) -> dict[str, Any]:
        reset_metrics = self.state.machine_state in {MachineState.UNKNOWN, MachineState.IDLE}
        if speed_kmh is not None:
            self.state.target_speed_kmh = self.state.validate_speed(speed_kmh)
        await self.connect()
        await self.request_control()
        if reset_metrics:
            self.state.reset_session_metrics()
        await self._send_control(set_target_speed_command(self.state.target_speed_kmh))
        await self._send_control(start_or_resume_command())
        self.state.set_machine(MachineState.STARTING)
        await self._publish()
        await self._restore_target_speed()
        await self._publish()
        return self.state.snapshot()

    async def _send_and_set_state(self, payload: bytes, state: MachineState) -> dict[str, Any]:
        await self._send_control(payload)
        self.state.set_machine(state)
        await self._publish()
        return self.state.snapshot()

    async def _restore_target_speed(self) -> None:
        for _ in range(TARGET_RESTORE_ATTEMPTS):
            await asyncio.sleep(TARGET_RESTORE_INTERVAL_SECONDS)
            await self._send_control(set_target_speed_command(self.state.target_speed_kmh))

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
            self.state.set_connection(ConnectionState.ERROR)
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
        self.state.apply_notification(sender_uuid, bytes(data))
        asyncio.create_task(self._publish())

    async def _publish(self) -> None:
        snapshot = self.state.snapshot()
        for queue in list(self._subscribers):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(snapshot)
