import asyncio

import pytest

import hometro_fitshow_ble.controller as controller_module
from hometro_fitshow_ble.controller import MachineState, TreadmillController
from hometro_fitshow_ble.fitshow_oem import FITSHOW_NOTIFY_UUID


class ContractFakeBleakClient:
    attempts = 0
    instances = []

    def __init__(self, address: str, *, timeout: float) -> None:
        self.address = address
        self.timeout = timeout
        self.is_connected = False
        self.notifications = []
        self.writes = []
        ContractFakeBleakClient.instances.append(self)

    async def connect(self) -> None:
        ContractFakeBleakClient.attempts += 1
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False

    async def start_notify(self, char_uuid, callback) -> None:
        self.notifications.append((char_uuid, callback))

    async def stop_notify(self, char_uuid) -> None:
        self.notifications = [
            notification for notification in self.notifications if notification[0] != char_uuid
        ]

    async def write_gatt_char(self, char_uuid, payload: bytes, *, response: bool) -> None:
        self.writes.append((char_uuid, payload, response))


def setup_contract_bleak(monkeypatch: pytest.MonkeyPatch) -> None:
    ContractFakeBleakClient.attempts = 0
    ContractFakeBleakClient.instances = []

    async def fake_release(address: str) -> bool:
        return True

    async def fake_is_system_connected(address: str) -> bool:
        return False

    monkeypatch.setattr(controller_module, "BleakClient", ContractFakeBleakClient)
    monkeypatch.setattr(controller_module, "is_system_connected", fake_is_system_connected)
    monkeypatch.setattr(controller_module, "release_system_connection", fake_release)


def control_writes() -> list[bytes]:
    return [
        payload
        for client in ContractFakeBleakClient.instances
        for _, payload, _ in client.writes
    ]


def assert_control_writes_allowing_request_control(expected: list[bytes]) -> None:
    writes = control_writes()
    assert writes in (expected, [b"\x00", *expected])


async def play(controller: TreadmillController) -> dict:
    if hasattr(controller, "play"):
        return await controller.play()
    return await controller.start()


async def pause_toggle(controller: TreadmillController) -> dict:
    assert hasattr(controller, "pause_toggle"), "controller must expose pause_toggle()"
    return await controller.pause_toggle()


def set_machine_state(controller: TreadmillController, state: MachineState) -> None:
    if hasattr(controller, "_set_machine_state"):
        controller._set_machine_state(state)
    else:
        controller.state.control_state = state.value


def test_set_speed_while_idle_updates_target_without_ble_speed_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_contract_bleak(monkeypatch)
    controller = TreadmillController("66:99:D4:F6:7B:30")

    state = asyncio.run(controller.set_speed(4.0))

    assert state["target_speed_kmh"] == 4.0
    assert control_writes() == []


def test_play_with_target_4_requests_control_sets_speed_then_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_contract_bleak(monkeypatch)
    controller = TreadmillController("66:99:D4:F6:7B:30")
    controller.state.target_speed_kmh = 4.0

    asyncio.run(play(controller))

    assert control_writes() == [
        b"\x00",
        b"\x02\x90\x01",
        b"\x07",
    ]


def test_pause_toggle_while_running_sends_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_contract_bleak(monkeypatch)
    controller = TreadmillController("66:99:D4:F6:7B:30")
    set_machine_state(controller, MachineState.RUNNING)

    asyncio.run(pause_toggle(controller))

    assert_control_writes_allowing_request_control([b"\x08\x02"])


@pytest.mark.parametrize("state", [MachineState.IDLE, MachineState.PAUSED])
def test_pause_toggle_while_idle_or_paused_starts_with_backend_target(
    monkeypatch: pytest.MonkeyPatch,
    state: MachineState,
) -> None:
    setup_contract_bleak(monkeypatch)
    controller = TreadmillController("66:99:D4:F6:7B:30")
    controller.state.target_speed_kmh = 4.0
    set_machine_state(controller, state)

    asyncio.run(pause_toggle(controller))

    assert control_writes() == [
        b"\x00",
        b"\x02\x90\x01",
        b"\x07",
    ]


def test_stop_sends_stop_and_sets_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    setup_contract_bleak(monkeypatch)
    controller = TreadmillController("66:99:D4:F6:7B:30")
    set_machine_state(controller, MachineState.RUNNING)

    state = asyncio.run(controller.stop())

    assert_control_writes_allowing_request_control([b"\x08\x01"])
    assert state["machine_state"] == MachineState.IDLE
    assert state["running"] is False
    assert state["paused"] is False


def test_fitshow_idle_after_pause_is_accepted_as_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    setup_contract_bleak(monkeypatch)
    controller = TreadmillController("66:99:D4:F6:7B:30")

    async def exercise() -> dict:
        await controller.pause()
        controller._handle_notification(FITSHOW_NOTIFY_UUID, bytearray.fromhex("02 51 00 51 03"))
        await asyncio.sleep(0)
        return controller.state.snapshot()

    state = asyncio.run(exercise())

    assert state["machine_state"] == MachineState.IDLE
    assert state["paused"] is False
