"""Small protocol helpers for reverse engineering captures.

This module intentionally does not pretend to know the HomeTro/FitShow protocol
yet. Use it to test common framing/checksum hypotheses against real captures.
"""

from __future__ import annotations


def clean_hex(value: str) -> str:
    """Normalize common human hex formats into a compact lowercase string."""
    cleaned = (
        value.strip()
        .lower()
        .replace("0x", "")
        .replace(",", " ")
        .replace(":", " ")
        .replace("-", " ")
        .replace("_", " ")
    )
    cleaned = "".join(cleaned.split())
    if len(cleaned) % 2:
        raise ValueError(f"hex string must contain complete bytes: {value!r}")
    try:
        bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ValueError(f"invalid hex string: {value!r}") from exc
    return cleaned


def bytes_from_hex(value: str) -> bytes:
    return bytes.fromhex(clean_hex(value))


def hex_from_bytes(value: bytes | bytearray | memoryview) -> str:
    return bytes(value).hex(" ")


def sum8(value: bytes) -> int:
    return sum(value) & 0xFF


def xor8(value: bytes) -> int:
    result = 0
    for byte in value:
        result ^= byte
    return result


def append_sum8(value: bytes) -> bytes:
    return value + bytes([sum8(value)])


def append_xor8(value: bytes) -> bytes:
    return value + bytes([xor8(value)])
