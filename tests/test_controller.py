import asyncio

import pytest

import hometro_fitshow_ble.controller as controller_module
from hometro_fitshow_ble.controller import ConnectionState, TreadmillController
from hometro_fitshow_ble.ftms import TREADMILL_DATA_UUID


class FakeBleakClient:
    attempts = 0
    fail_attempts = 0
    instances = []

    def __init__(self, address: str, *, timeout: float) -> None:
        self.address = address
        self.timeout = timeout
        self.is_connected = False
        self.disconnected = False
        self.notifications = []
        self.writes = []
        FakeBleakClient.instances.append(self)

    async def connect(self) -> None:
        FakeBleakClient.attempts += 1
        if FakeBleakClient.attempts <= FakeBleakClient.fail_attempts:
            self.is_connected = True
            raise RuntimeError("bluez stale connection")
        self.is_connected = True

    async def disconnect(self) -> None:
        self.disconnected = True
        self.is_connected = False

    async def start_notify(self, char_uuid, callback) -> None:
        self.notifications.append((char_uuid, callback))

    async def write_gatt_char(self, char_uuid, payload: bytes, *, response: bool) -> None:
        self.writes.append((char_uuid, payload, response))


def setup_fake_bleak(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_attempts: int,
    system_connected: bool = False,
) -> list[str]:
    FakeBleakClient.attempts = 0
    FakeBleakClient.fail_attempts = fail_attempts
    FakeBleakClient.instances = []
    releases: list[str] = []

    async def fake_release(address: str) -> bool:
        releases.append(address)
        return True

    async def fake_is_system_connected(address: str) -> bool:
        return system_connected

    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(controller_module, "BleakClient", FakeBleakClient)
    monkeypatch.setattr(controller_module, "is_system_connected", fake_is_system_connected)
    monkeypatch.setattr(controller_module, "release_system_connection", fake_release)
    monkeypatch.setattr(controller_module.asyncio, "sleep", fake_sleep)
    return releases


def test_connect_retries_after_releasing_stale_system_connection(monkeypatch: pytest.MonkeyPatch):
    releases = setup_fake_bleak(monkeypatch, fail_attempts=1)
    controller = TreadmillController("66:99:D4:F6:7B:30")

    state = asyncio.run(controller.connect())

    assert state["connected"] is True
    assert state["connection_state"] == ConnectionState.CONNECTED
    assert state["last_error"] is None
    assert FakeBleakClient.attempts == 2
    assert releases == ["66:99:D4:F6:7B:30"]
    assert FakeBleakClient.instances[0].disconnected is True


def test_connect_releases_known_system_connection_before_first_attempt(
    monkeypatch: pytest.MonkeyPatch,
):
    releases = setup_fake_bleak(monkeypatch, fail_attempts=0, system_connected=True)
    controller = TreadmillController("66:99:D4:F6:7B:30")

    state = asyncio.run(controller.connect())

    assert state["connection_state"] == ConnectionState.CONNECTED
    assert FakeBleakClient.attempts == 1
    assert releases == ["66:99:D4:F6:7B:30"]


def test_connect_enters_error_state_after_retry_failure(monkeypatch: pytest.MonkeyPatch):
    releases = setup_fake_bleak(monkeypatch, fail_attempts=2)
    controller = TreadmillController("66:99:D4:F6:7B:30")

    with pytest.raises(RuntimeError, match="bluez stale connection"):
        asyncio.run(controller.connect())

    state = controller.state.snapshot()
    assert state["connected"] is False
    assert state["connection_state"] == ConnectionState.ERROR
    assert state["last_error"] == "bluez stale connection"
    assert FakeBleakClient.attempts == 2
    assert releases == ["66:99:D4:F6:7B:30"]
    assert all(client.disconnected for client in FakeBleakClient.instances)


def test_treadmill_data_updates_observed_speed_without_overwriting_target(
    monkeypatch: pytest.MonkeyPatch,
):
    setup_fake_bleak(monkeypatch, fail_attempts=0)
    controller = TreadmillController("66:99:D4:F6:7B:30")

    async def exercise() -> None:
        await controller.connect()
        await controller.set_speed(3.0)
        controller._handle_notification(
            TREADMILL_DATA_UUID,
            bytearray.fromhex("84 04 64 00 00 00 00 00 00 ff ff ff 00 00"),
        )
        await asyncio.sleep(0)

    asyncio.run(exercise())

    assert controller.state.speed_kmh == 1.0
    assert controller.state.target_speed_kmh == 3.0


def test_observed_speed_does_not_overwrite_software_target(monkeypatch: pytest.MonkeyPatch):
    setup_fake_bleak(monkeypatch, fail_attempts=0)
    controller = TreadmillController("66:99:D4:F6:7B:30")

    async def exercise() -> None:
        await controller.connect()
        await controller.set_speed(4.0)
        controller._handle_notification(
            TREADMILL_DATA_UUID,
            bytearray.fromhex("84 04 64 00 00 00 00 00 00 ff ff ff 00 00"),
        )
        await asyncio.sleep(0)

    asyncio.run(exercise())

    assert controller.state.speed_kmh == 1.0
    assert controller.state.target_speed_kmh == 4.0


def test_slowdown_notification_below_command_minimum_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
):
    setup_fake_bleak(monkeypatch, fail_attempts=0)
    controller = TreadmillController("66:99:D4:F6:7B:30")

    async def exercise() -> None:
        await controller.connect()
        await controller.set_speed(4.0)
        controller._handle_notification(
            TREADMILL_DATA_UUID,
            bytearray.fromhex("84 04 3c 00 00 00 00 00 00 ff ff ff 00 00"),
        )
        await asyncio.sleep(0)

    asyncio.run(exercise())

    assert controller.state.speed_kmh == 0.6
    assert controller.state.target_speed_kmh == 4.0
