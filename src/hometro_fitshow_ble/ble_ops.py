from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from bleak import BleakClient, BleakScanner

from .capture import append_jsonl, dump_json
from .fitshow_oem import FITSHOW_NOTIFY_UUID, parse_fitshow_frame
from .ftms import (
    FITNESS_MACHINE_CONTROL_POINT_UUID,
    FITNESS_MACHINE_STATUS_UUID,
    TREADMILL_DATA_UUID,
    parse_control_point_response,
    parse_treadmill_data,
    request_control_command,
    set_target_speed_command,
    start_or_resume_command,
    stop_command,
)
from .models import (
    AdvertisementRecord,
    CharacteristicRecord,
    DescriptorRecord,
    NotificationEvent,
    ServiceRecord,
    WriteEvent,
    utc_now,
)
from .protocol import bytes_from_hex, hex_from_bytes
from .replay import ReplayItem, parse_replay_file
from .system_ble import known_system_devices


def _sort_advertisements(rows: list[AdvertisementRecord]) -> list[AdvertisementRecord]:
    return sorted(rows, key=lambda row: (row.rssi is None, -(row.rssi or -999), row.address or ""))


async def scan_devices(timeout: float, contains: str | None = None) -> list[AdvertisementRecord]:
    discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
    rows = [
        AdvertisementRecord.from_bleak(device, advertisement)
        for device, advertisement in discovered.values()
    ]
    seen = {row.address for row in rows}
    rows.extend(
        AdvertisementRecord(
            address=address,
            name=name,
            details="known system device",
            rssi=None,
            local_name=name,
            manufacturer_data={},
            service_data={},
            service_uuids=[],
            tx_power=None,
        )
        for address, name in await known_system_devices()
        if address not in seen
    )
    return _sort_advertisements([row for row in rows if row.matches(contains)])


async def get_services(client: BleakClient) -> Any:
    services = getattr(client, "services", None)
    if services:
        return services
    get_services_fn = getattr(client, "get_services", None)
    if get_services_fn is None:
        raise RuntimeError("Bleak did not expose services after connect")
    return await get_services_fn()


def service_to_record(service: Any) -> ServiceRecord:
    return ServiceRecord(
        uuid=service.uuid,
        description=getattr(service, "description", None),
        handle=getattr(service, "handle", None),
        characteristics=[
            CharacteristicRecord(
                uuid=char.uuid,
                description=getattr(char, "description", None),
                handle=getattr(char, "handle", None),
                properties=list(getattr(char, "properties", []) or []),
                descriptors=[
                    DescriptorRecord(
                        uuid=descriptor.uuid,
                        handle=getattr(descriptor, "handle", None),
                        description=getattr(descriptor, "description", None),
                    )
                    for descriptor in getattr(char, "descriptors", []) or []
                ],
            )
            for char in service.characteristics
        ],
    )


def notifiable_characteristics(services: Iterable[Any]) -> list[Any]:
    chars: list[Any] = []
    for service in services:
        for char in service.characteristics:
            properties = set(char.properties or [])
            if properties.intersection({"notify", "indicate"}):
                chars.append(char)
    return chars


async def collect_gatt(
    address: str,
    *,
    timeout: float,
    read_values: bool,
) -> dict[str, Any]:
    async with BleakClient(address, timeout=timeout) as client:
        services = await get_services(client)
        payload: dict[str, Any] = {
            "captured_at": utc_now(),
            "address": address,
            "connected": client.is_connected,
            "services": [service_to_record(service).to_json() for service in services],
        }

        if read_values:
            reads: list[dict[str, Any]] = []
            for service in services:
                for char in service.characteristics:
                    if "read" not in (char.properties or []):
                        continue
                    try:
                        value = await client.read_gatt_char(char.uuid)
                        reads.append({"uuid": char.uuid, "ok": True, "hex": hex_from_bytes(value)})
                    except Exception as exc:
                        reads.append({"uuid": char.uuid, "ok": False, "error": repr(exc)})
            payload["reads"] = reads

        return payload


async def monitor_notifications(
    address: str,
    *,
    chars: list[str] | None,
    timeout: float,
    duration: float | None,
    out: Path | None,
    on_event: Callable[[NotificationEvent], None],
) -> None:
    async with BleakClient(address, timeout=timeout) as client:
        services = await get_services(client)
        selected_chars = chars or [char.uuid for char in notifiable_characteristics(services)]
        if not selected_chars:
            raise RuntimeError("No notify/indicate characteristics found; pass --char explicitly.")

        def callback(sender: Any, data: bytearray) -> None:
            sender_uuid = getattr(sender, "uuid", str(sender))
            raw = bytes(data)
            decoded = None
            if sender_uuid == TREADMILL_DATA_UUID:
                treadmill_data = parse_treadmill_data(raw)
                decoded = treadmill_data.to_json() if treadmill_data else None
            elif sender_uuid == FITSHOW_NOTIFY_UUID:
                fitshow_frame = parse_fitshow_frame(raw)
                decoded = fitshow_frame.to_json() if fitshow_frame else None
            event = NotificationEvent(
                ts=utc_now(),
                address=address,
                char=sender_uuid,
                hex=hex_from_bytes(raw),
                length=len(data),
                decoded=decoded,
            )
            on_event(event)
            append_jsonl(out, event.to_json())

        started: list[str] = []
        try:
            for char_uuid in selected_chars:
                await client.start_notify(char_uuid, callback)
                started.append(char_uuid)

            if duration is None:
                while True:
                    await asyncio.sleep(3600)
            else:
                await asyncio.sleep(duration)
        finally:
            for char_uuid in started:
                with contextlib.suppress(Exception):
                    await client.stop_notify(char_uuid)


async def write_payload(
    address: str,
    *,
    char: str,
    raw_hex: str,
    timeout: float,
    response: bool,
    read_before: bool,
    read_after: bool,
    read_after_delay: float,
    out: Path | None,
) -> None:
    payload = bytes_from_hex(raw_hex)
    async with BleakClient(address, timeout=timeout) as client:
        if read_before:
            value = await client.read_gatt_char(char)
            print(f"BEFORE {char}: {hex_from_bytes(value)}")

        await client.write_gatt_char(char, payload, response=response)
        event = WriteEvent(
            ts=utc_now(),
            address=address,
            char=char,
            hex=hex_from_bytes(payload),
            response=response,
        )
        append_jsonl(out, event.to_json())
        print(f"WROTE {char}: {event.hex} response={response}")

        if read_after:
            await asyncio.sleep(read_after_delay)
            value = await client.read_gatt_char(char)
            print(f"AFTER  {char}: {hex_from_bytes(value)}")


async def write_ftms_control_point(
    address: str,
    *,
    payload: bytes,
    timeout: float,
    out: Path | None,
) -> None:
    async with BleakClient(address, timeout=timeout) as client:
        responses: list[str] = []

        def callback(sender: Any, data: bytearray) -> None:
            raw = bytes(data)
            response = parse_control_point_response(raw)
            event = NotificationEvent(
                ts=utc_now(),
                address=address,
                char=getattr(sender, "uuid", FITNESS_MACHINE_CONTROL_POINT_UUID),
                hex=hex_from_bytes(raw),
                length=len(raw),
            )
            append_jsonl(out, event.to_json())
            if response is None:
                text = f"FTMS indication: {event.hex}"
            else:
                text = (
                    "FTMS response: "
                    f"{response.request_name} -> {response.result_name} ({event.hex})"
                )
            responses.append(text)
            print(text)

        await client.start_notify(FITNESS_MACHINE_CONTROL_POINT_UUID, callback)
        try:
            await client.write_gatt_char(
                FITNESS_MACHINE_CONTROL_POINT_UUID,
                payload,
                response=True,
            )
            event = WriteEvent(
                ts=utc_now(),
                address=address,
                char=FITNESS_MACHINE_CONTROL_POINT_UUID,
                hex=hex_from_bytes(payload),
                response=True,
            )
            append_jsonl(out, event.to_json())
            print(f"WROTE FTMS control point: {event.hex}")
            await asyncio.sleep(1.0)
            if not responses:
                print("No FTMS control point indication received within 1s.")
        finally:
            with contextlib.suppress(Exception):
                await client.stop_notify(FITNESS_MACHINE_CONTROL_POINT_UUID)


async def run_ftms_session(
    address: str,
    *,
    speed_kmh: float,
    duration: float | None,
    timeout: float,
    out: Path | None,
    on_event: Callable[[NotificationEvent], None],
) -> None:
    async with BleakClient(address, timeout=timeout) as client:
        services = await get_services(client)
        selected_chars = [
            char.uuid
            for char in notifiable_characteristics(services)
            if char.uuid
            in {
                FITNESS_MACHINE_CONTROL_POINT_UUID,
                FITNESS_MACHINE_STATUS_UUID,
                TREADMILL_DATA_UUID,
                FITSHOW_NOTIFY_UUID,
            }
        ]

        def notify_callback(sender: Any, data: bytearray) -> None:
            sender_uuid = getattr(sender, "uuid", str(sender))
            raw = bytes(data)
            decoded = None
            if sender_uuid == FITNESS_MACHINE_CONTROL_POINT_UUID:
                response = parse_control_point_response(raw)
                decoded = (
                    {
                        "type": "ftms_control_response",
                        "request": response.request_name,
                        "result": response.result_name,
                    }
                    if response
                    else None
                )
            elif sender_uuid == TREADMILL_DATA_UUID:
                treadmill_data = parse_treadmill_data(raw)
                decoded = treadmill_data.to_json() if treadmill_data else None
            elif sender_uuid == FITSHOW_NOTIFY_UUID:
                fitshow_frame = parse_fitshow_frame(raw)
                decoded = fitshow_frame.to_json() if fitshow_frame else None

            event = NotificationEvent(
                ts=utc_now(),
                address=address,
                char=sender_uuid,
                hex=hex_from_bytes(raw),
                length=len(raw),
                decoded=decoded,
            )
            append_jsonl(out, event.to_json())
            on_event(event)

        started_notify: list[str] = []

        async def send_control(payload: bytes) -> None:
            await client.write_gatt_char(
                FITNESS_MACHINE_CONTROL_POINT_UUID,
                payload,
                response=True,
            )
            event = WriteEvent(
                ts=utc_now(),
                address=address,
                char=FITNESS_MACHINE_CONTROL_POINT_UUID,
                hex=hex_from_bytes(payload),
                response=True,
            )
            append_jsonl(out, event.to_json())
            print(f"WROTE FTMS control point: {event.hex}")

        try:
            for char_uuid in selected_chars:
                await client.start_notify(char_uuid, notify_callback)
                started_notify.append(char_uuid)

            await send_control(request_control_command())
            await asyncio.sleep(0.25)
            await send_control(set_target_speed_command(speed_kmh))
            await asyncio.sleep(0.25)
            await send_control(start_or_resume_command())

            if duration is None:
                while True:
                    await asyncio.sleep(3600)
            else:
                await asyncio.sleep(duration)
        finally:
            with contextlib.suppress(Exception):
                await send_control(stop_command())
                await asyncio.sleep(1.0)
            for char_uuid in started_notify:
                with contextlib.suppress(Exception):
                    await client.stop_notify(char_uuid)


async def replay_writes(
    address: str,
    *,
    file: Path,
    fallback_char: str | None,
    timeout: float,
    response: bool,
    out: Path | None,
) -> list[ReplayItem]:
    items = parse_replay_file(file, fallback_char, response)
    async with BleakClient(address, timeout=timeout) as client:
        for index, item in enumerate(items, start=1):
            if item.delay_ms:
                await asyncio.sleep(item.delay_ms / 1000)
            await client.write_gatt_char(item.char, item.data, response=item.response)
            event = WriteEvent(
                ts=utc_now(),
                address=address,
                char=item.char,
                hex=hex_from_bytes(item.data),
                response=item.response,
                index=index,
            )
            append_jsonl(out, event.to_json())
            print(f"{index:03d} {item.char}: {event.hex} response={item.response}")
    return items


def write_scan_json(path: Path | None, rows: list[AdvertisementRecord]) -> None:
    dump_json(path, {"captured_at": utc_now(), "devices": [row.to_json() for row in rows]})
