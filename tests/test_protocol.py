from hometro_fitshow_ble.protocol import (
    append_sum8,
    append_xor8,
    bytes_from_hex,
    hex_from_bytes,
    sum8,
    xor8,
)


def test_hex_normalization_accepts_common_separators() -> None:
    assert bytes_from_hex("0xaa, 01:02-03") == b"\xaa\x01\x02\x03"


def test_hex_formatting_uses_spaces() -> None:
    assert hex_from_bytes(b"\xaa\x01\x02") == "aa 01 02"


def test_checksum_helpers() -> None:
    payload = b"\x01\x02\x03"
    assert sum8(payload) == 0x06
    assert xor8(payload) == 0x00
    assert append_sum8(payload) == b"\x01\x02\x03\x06"
    assert append_xor8(payload) == b"\x01\x02\x03\x00"
