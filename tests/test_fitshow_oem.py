from hometro_fitshow_ble.fitshow_oem import parse_fitshow_frame, xor_checksum


def test_vendor_checksum_is_xor_over_body() -> None:
    body = bytes.fromhex("51 03 28 00 04 00 01 00 00 00 01 00 00 00")

    assert xor_checksum(body) == 0x7E


def test_parse_idle_frame() -> None:
    frame = parse_fitshow_frame(bytes.fromhex("02 51 00 51 03"))

    assert frame is not None
    assert frame.checksum_ok is True
    assert frame.state_name == "idle"


def test_parse_countdown_frame() -> None:
    frame = parse_fitshow_frame(bytes.fromhex("02 51 02 03 50 03"))

    assert frame is not None
    assert frame.state_name == "countdown"
    assert frame.countdown_s == 3


def test_parse_running_frame() -> None:
    frame = parse_fitshow_frame(
        bytes.fromhex("02 51 03 28 00 04 00 01 00 00 00 01 00 00 00 7e 03")
    )

    assert frame is not None
    assert frame.state_name == "running"
    assert frame.speed_kmh == 4.0
    assert frame.elapsed_s == 4
    assert frame.distance_m == 1
