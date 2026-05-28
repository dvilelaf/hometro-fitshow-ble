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


def test_generic_ble_device_is_not_known_treadmill() -> None:
    assert not advertisement(local_name="Keyboard").is_known_treadmill()


def test_generic_fitness_machine_service_is_not_enough() -> None:
    record = advertisement(local_name="Bike", service_uuids=[FITNESS_MACHINE_SERVICE_UUID])

    assert not record.is_known_treadmill()
