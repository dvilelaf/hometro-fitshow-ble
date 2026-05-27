from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .ble_ops import (
    collect_gatt,
    monitor_notifications,
    replay_writes,
    run_ftms_session,
    scan_devices,
    write_ftms_control_point,
    write_payload,
    write_scan_json,
)
from .capture import dump_json
from .ftms import (
    pause_command,
    request_control_command,
    set_target_speed_command,
    start_or_resume_command,
    stop_command,
)
from .models import NotificationEvent
from .web import run_server


async def scan(args: argparse.Namespace) -> None:
    print(f"Scanning for {args.timeout:.1f}s...")
    rows = await scan_devices(timeout=args.timeout, contains=args.contains)

    for row in rows:
        name = row.local_name or row.name or "<no name>"
        address = row.address or "<no address>"
        rssi = row.rssi if row.rssi is not None else "?"
        services = ", ".join(row.service_uuids[:3])
        print(f"{address:>36}  RSSI {rssi:>4}  {name}  {services}")

    if args.out:
        write_scan_json(args.out, rows)


async def gatt(args: argparse.Namespace) -> None:
    payload = await collect_gatt(args.address, timeout=args.timeout, read_values=args.read)
    print(f"Connected: {payload['connected']}")

    for service in payload["services"]:
        print(f"\nService {service['uuid']}  {service.get('description') or ''}")
        for char in service["characteristics"]:
            properties = ",".join(char["properties"])
            print(f"  Char {char['uuid']}  [{properties}]  {char.get('description') or ''}")

    for read in payload.get("reads", []):
        if read["ok"]:
            print(f"READ {read['uuid']}: {read['hex']}")
        else:
            print(f"READ {read['uuid']}: ERROR {read['error']}")

    dump_json(args.out, payload)


async def notify(args: argparse.Namespace) -> None:
    chars = args.char or None
    if chars:
        print("Subscribing to:")
        for char_uuid in chars:
            print(f"  {char_uuid}")
    else:
        print("Subscribing to all notify/indicate characteristics...")

    def print_event(event: NotificationEvent) -> None:
        suffix = ""
        if event.decoded:
            speed = event.decoded.get("instantaneous_speed_kmh")
            speed = event.decoded.get("speed_kmh", speed)
            distance = event.decoded.get("total_distance_m")
            distance = event.decoded.get("distance_m", distance)
            elapsed = event.decoded.get("elapsed_time_s")
            elapsed = event.decoded.get("elapsed_s", elapsed)
            calories = event.decoded.get("total_energy_kcal")
            parts = []
            state = event.decoded.get("state")
            if state:
                parts.append(f"state={state}")
            if speed is not None:
                parts.append(f"speed={speed:.2f}km/h")
            if distance is not None:
                parts.append(f"distance={distance}m")
            if elapsed is not None:
                parts.append(f"elapsed={elapsed}s")
            if calories is not None:
                parts.append(f"calories={calories}kcal")
            if parts:
                suffix = "  " + " ".join(parts)
        print(f"{event.ts}  {event.char}  {event.hex}{suffix}")

    print("Listening. Press Ctrl+C to stop.")
    await monitor_notifications(
        args.address,
        chars=chars,
        timeout=args.timeout,
        duration=args.duration,
        out=args.out,
        on_event=print_event,
    )


async def write(args: argparse.Namespace) -> None:
    await write_payload(
        args.address,
        char=args.char,
        raw_hex=args.hex,
        timeout=args.timeout,
        response=args.response,
        read_before=args.read_before,
        read_after=args.read_after,
        read_after_delay=args.read_after_delay,
        out=args.out,
    )


async def replay(args: argparse.Namespace) -> None:
    print(f"Replaying writes from {args.file}")
    items = await replay_writes(
        args.address,
        file=args.file,
        fallback_char=args.char,
        timeout=args.timeout,
        response=args.response,
        out=args.out,
    )
    print(f"Replayed {len(items)} write(s)")


async def ftms(args: argparse.Namespace) -> None:
    command_builders = {
        "request-control": request_control_command,
        "start": start_or_resume_command,
        "stop": stop_command,
        "pause": pause_command,
    }
    if args.action == "speed":
        payload = set_target_speed_command(args.speed)
    else:
        payload = command_builders[args.action]()

    await write_ftms_control_point(
        args.address,
        payload=payload,
        timeout=args.timeout,
        out=args.out,
    )


async def session(args: argparse.Namespace) -> None:
    print(
        f"Starting FTMS session at {args.speed:.2f} km/h"
        + (f" for {args.duration:.1f}s." if args.duration is not None else ".")
    )
    print("Press Ctrl+C to stop.")

    def print_event(event: NotificationEvent) -> None:
        if not event.decoded:
            return
        event_type = event.decoded.get("type")
        if event_type == "ftms_control_response":
            print(f"{event.ts}  {event.decoded['request']} -> {event.decoded['result']}")
            return
        speed = event.decoded.get("instantaneous_speed_kmh")
        speed = event.decoded.get("speed_kmh", speed)
        distance = event.decoded.get("total_distance_m")
        distance = event.decoded.get("distance_m", distance)
        elapsed = event.decoded.get("elapsed_time_s")
        elapsed = event.decoded.get("elapsed_s", elapsed)
        calories = event.decoded.get("total_energy_kcal")
        if speed is not None:
            suffix = f"speed={speed:.2f}km/h"
            if distance is not None:
                suffix += f" distance={distance}m"
            if elapsed is not None:
                suffix += f" elapsed={elapsed}s"
            if calories is not None:
                suffix += f" calories={calories}kcal"
            print(f"{event.ts}  {suffix}")

    await run_ftms_session(
        args.address,
        speed_kmh=args.speed,
        duration=args.duration,
        timeout=args.timeout,
        out=args.out,
        on_event=print_event,
    )


def web(args: argparse.Namespace) -> None:
    run_server(args.address, host=args.host, port=args.port, timeout=args.timeout)


async def run(args: argparse.Namespace) -> None:
    await args.func(args)


def add_common_connect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "address",
        help="BLE address. On macOS this is usually a CoreBluetooth UUID.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Connection timeout in seconds.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hometro-ble",
        description="BLE reverse engineering CLI for HomeTro / FitShow treadmills.",
    )
    subparsers = parser.add_subparsers(required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan nearby BLE advertisements.")
    scan_parser.add_argument("--timeout", type=float, default=10.0)
    scan_parser.add_argument("--contains", help="Filter by name/address/service substring.")
    scan_parser.add_argument("--out", type=Path, help="Write JSON scan result.")
    scan_parser.set_defaults(func=scan)

    gatt_parser = subparsers.add_parser("gatt", help="List GATT services and characteristics.")
    add_common_connect_args(gatt_parser)
    gatt_parser.add_argument(
        "--read",
        action="store_true",
        help="Try to read readable characteristics.",
    )
    gatt_parser.add_argument("--out", type=Path, help="Write JSON GATT result.")
    gatt_parser.set_defaults(func=gatt)

    notify_parser = subparsers.add_parser("notify", help="Monitor notifications/indications.")
    add_common_connect_args(notify_parser)
    notify_parser.add_argument(
        "--char",
        action="append",
        help="Characteristic UUID to monitor. Repeat for multiple. Defaults to all notifiable.",
    )
    notify_parser.add_argument(
        "--duration",
        type=float,
        help="Seconds to listen. Default: until Ctrl+C.",
    )
    notify_parser.add_argument("--out", type=Path, help="Append NDJSON notification events.")
    notify_parser.set_defaults(func=notify)

    write_parser = subparsers.add_parser("write", help="Write a hex payload to a characteristic.")
    add_common_connect_args(write_parser)
    write_parser.add_argument("--char", required=True, help="Writable characteristic UUID.")
    write_parser.add_argument("--hex", required=True, help='Payload, e.g. "aa 01 02 ad".')
    write_parser.add_argument("--response", action="store_true", help="Use write-with-response.")
    write_parser.add_argument(
        "--read-before",
        action="store_true",
        help="Read the same characteristic first.",
    )
    write_parser.add_argument(
        "--read-after",
        action="store_true",
        help="Read the same characteristic after.",
    )
    write_parser.add_argument("--read-after-delay", type=float, default=0.2)
    write_parser.add_argument("--out", type=Path, help="Append NDJSON write events.")
    write_parser.set_defaults(func=write)

    replay_parser = subparsers.add_parser("replay", help="Replay hex writes from text or NDJSON.")
    add_common_connect_args(replay_parser)
    replay_parser.add_argument("--file", type=Path, required=True, help="Input replay file.")
    replay_parser.add_argument("--char", help="Fallback writable characteristic UUID.")
    replay_parser.add_argument(
        "--response",
        action="store_true",
        help="Default to write-with-response.",
    )
    replay_parser.add_argument("--out", type=Path, help="Append NDJSON write events.")
    replay_parser.set_defaults(func=replay)

    ftms_parser = subparsers.add_parser("ftms", help="Send standard FTMS control commands.")
    add_common_connect_args(ftms_parser)
    ftms_parser.add_argument(
        "action",
        choices=("request-control", "start", "stop", "pause", "speed"),
        help="FTMS control point action.",
    )
    ftms_parser.add_argument("--speed", type=float, help="Target speed in km/h for action=speed.")
    ftms_parser.add_argument("--out", type=Path, help="Append NDJSON FTMS events.")
    ftms_parser.set_defaults(func=ftms)

    session_parser = subparsers.add_parser(
        "session",
        help="Run a controlled FTMS session and stop automatically.",
    )
    add_common_connect_args(session_parser)
    session_parser.add_argument("--speed", type=float, required=True, help="Target speed in km/h.")
    session_parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Seconds to run before stopping. Default: 10.",
    )
    session_parser.add_argument("--out", type=Path, help="Append NDJSON session events.")
    session_parser.set_defaults(func=session)

    web_parser = subparsers.add_parser("web", help="Run the local web control server.")
    add_common_connect_args(web_parser)
    web_parser.add_argument("--host", default="127.0.0.1", help="HTTP host. Default: 127.0.0.1.")
    web_parser.add_argument("--port", type=int, default=8000, help="HTTP port. Default: 8000.")
    web_parser.set_defaults(sync_func=web)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if sync_func := getattr(args, "sync_func", None):
        sync_func(args)
        return
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
