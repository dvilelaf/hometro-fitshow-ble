import asyncio

import hometro_fitshow_ble.ble_ops as ble_ops
from hometro_fitshow_ble.fitshow_oem import FITSHOW_SERVICE_UUID
from hometro_fitshow_ble.ftms import FITNESS_MACHINE_SERVICE_UUID
from hometro_fitshow_ble.models import AdvertisementRecord


def advertisement(
    *,
    name: str | None = None,
    local_name: str | None = None,
    service_uuids: list[str] | None = None,
) -> AdvertisementRecord:
    return AdvertisementRecord(
        address="66:99:D4:F6:7B:30",
        name=name,
        details="",
        rssi=-60,
        local_name=local_name,
        manufacturer_data={},
        service_data={},
        service_uuids=service_uuids or [],
        tx_power=None,
    )


def test_fitshow_ftms_advertisement_is_known_treadmill() -> None:
    record = advertisement(
        local_name="FS-0099C3",
        service_uuids=[FITNESS_MACHINE_SERVICE_UUID, FITSHOW_SERVICE_UUID],
    )

    assert record.is_known_treadmill()


def test_fitshow_name_is_known_treadmill_even_without_services() -> None:
    assert advertisement(local_name="FS-0099C3").is_known_treadmill()


def test_generic_ble_device_is_not_known_treadmill() -> None:
    assert not advertisement(local_name="Keyboard").is_known_treadmill()


def test_generic_fitness_machine_service_is_not_enough() -> None:
    record = advertisement(local_name="Bike", service_uuids=[FITNESS_MACHINE_SERVICE_UUID])

    assert not record.is_known_treadmill()


def test_scan_includes_known_system_treadmill_when_not_advertising(
    monkeypatch,
) -> None:
    async def fake_discover(*, timeout: float, return_adv: bool):
        return {}

    async def fake_known_system_devices():
        return [("66:99:D4:F6:7B:30", "FS-0099C3")]

    monkeypatch.setattr(ble_ops.BleakScanner, "discover", fake_discover)
    monkeypatch.setattr(ble_ops, "known_system_devices", fake_known_system_devices)

    rows = asyncio.run(ble_ops.scan_devices(timeout=0.1))

    assert rows[0].address == "66:99:D4:F6:7B:30"
    assert rows[0].is_known_treadmill()
