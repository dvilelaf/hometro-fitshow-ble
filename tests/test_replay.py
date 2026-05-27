from pathlib import Path

import pytest

from hometro_fitshow_ble.replay import parse_replay_file, parse_replay_line

CHAR_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"


def test_parse_plain_replay_line_uses_fallback_char() -> None:
    item = parse_replay_line("aa 01 02 ad", fallback_char=CHAR_UUID, response=False)

    assert item is not None
    assert item.char == CHAR_UUID
    assert item.data == b"\xaa\x01\x02\xad"
    assert item.response is False


def test_parse_json_replay_line() -> None:
    item = parse_replay_line(
        '{"char":"0000fff1-0000-1000-8000-00805f9b34fb","hex":"aa 01","response":true}',
        fallback_char=None,
        response=False,
    )

    assert item is not None
    assert item.char == "0000fff1-0000-1000-8000-00805f9b34fb"
    assert item.data == b"\xaa\x01"
    assert item.response is True


def test_parse_replay_file_reports_line_number(tmp_path: Path) -> None:
    path = tmp_path / "bad.ndjson"
    path.write_text("aa 0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="bad.ndjson:1"):
        parse_replay_file(path, fallback_char=CHAR_UUID, response=False)
