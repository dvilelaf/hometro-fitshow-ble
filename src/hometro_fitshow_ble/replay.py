from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .protocol import bytes_from_hex


@dataclass(frozen=True)
class ReplayItem:
    char: str
    data: bytes
    response: bool
    delay_ms: int = 0


def parse_replay_file(path: Path, fallback_char: str | None, response: bool) -> list[ReplayItem]:
    items: list[ReplayItem] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            parsed = parse_replay_line(line, fallback_char=fallback_char, response=response)
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
        if parsed is not None:
            items.append(parsed)
    return items


def parse_replay_line(
    line: str,
    *,
    fallback_char: str | None,
    response: bool,
) -> ReplayItem | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    if line.startswith("{"):
        record = json.loads(line)
        char = record.get("write_char") or record.get("char") or fallback_char
        raw_hex = record.get("hex")
        item_response = bool(record.get("response", response))
        delay_ms = int(record.get("delay_ms", 0))
    else:
        parts = line.split()
        if len(parts) >= 2 and "-" in parts[0]:
            char = parts[0]
            raw_hex = " ".join(parts[1:])
        else:
            char = fallback_char
            raw_hex = line
        item_response = response
        delay_ms = 0

    if not char:
        raise ValueError("missing characteristic UUID")
    if not raw_hex:
        raise ValueError("missing hex payload")

    return ReplayItem(
        char=char,
        data=bytes_from_hex(raw_hex),
        response=item_response,
        delay_ms=delay_ms,
    )
