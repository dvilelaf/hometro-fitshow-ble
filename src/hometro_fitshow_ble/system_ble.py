from __future__ import annotations

import asyncio
import shutil
import sys


async def known_system_devices(*, timeout: float = 3.0) -> list[tuple[str, str]]:
    if sys.platform != "linux" or not shutil.which("bluetoothctl"):
        return []

    process = await asyncio.create_subprocess_exec(
        "bluetoothctl",
        "devices",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return []

    rows: list[tuple[str, str]] = []
    for line in stdout.decode(errors="replace").splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) != 3:
            continue
        _, address, name = parts
        if address:
            rows.append((address, name))
    return rows


async def release_system_connection(address: str, *, timeout: float = 5.0) -> bool:
    """Ask the OS Bluetooth stack to release a stale BLE connection.

    BlueZ can keep a device marked as connected after a failed Bleak connect.
    This helper is intentionally best-effort and currently only does work on
    Linux systems with bluetoothctl available.
    """
    if sys.platform != "linux" or not shutil.which("bluetoothctl"):
        return False

    process = await asyncio.create_subprocess_exec(
        "bluetoothctl",
        "disconnect",
        address,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return False

    output = (stdout + stderr).decode(errors="replace").lower()
    return process.returncode == 0 or "successful disconnected" in output


async def is_system_connected(address: str, *, timeout: float = 3.0) -> bool:
    if sys.platform != "linux" or not shutil.which("bluetoothctl"):
        return False

    process = await asyncio.create_subprocess_exec(
        "bluetoothctl",
        "info",
        address,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return False

    output = (stdout + stderr).decode(errors="replace").lower()
    return "connected: yes" in output
