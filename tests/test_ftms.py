from hometro_fitshow_ble.ftms import (
    ControlPointResultCode,
    parse_control_point_response,
    parse_treadmill_data,
    pause_command,
    request_control_command,
    set_target_speed_command,
    start_or_resume_command,
    stop_command,
)


def test_basic_ftms_commands() -> None:
    assert request_control_command() == b"\x00"
    assert start_or_resume_command() == b"\x07"
    assert stop_command() == b"\x08\x01"
    assert pause_command() == b"\x08\x02"


def test_set_target_speed_uses_hundredths_of_kmh_little_endian() -> None:
    assert set_target_speed_command(1.0) == b"\x02\x64\x00"
    assert set_target_speed_command(12.3) == b"\x02\xce\x04"


def test_parse_control_point_response() -> None:
    response = parse_control_point_response(b"\x80\x00\x01")

    assert response is not None
    assert response.request_name == "request_control"
    assert response.result_code == ControlPointResultCode.SUCCESS
    assert response.result_name == "success"


def test_parse_idle_treadmill_data() -> None:
    data = parse_treadmill_data(bytes.fromhex("84 04 00 00 00 00 00 00 00 ff ff ff 00 00"))

    assert data is not None
    assert data.instantaneous_speed_kmh == 0
    assert data.total_distance_m == 0
    assert data.total_energy_kcal == 0
    assert data.elapsed_time_s == 0


def test_parse_treadmill_data_with_speed_and_distance() -> None:
    data = parse_treadmill_data(bytes.fromhex("84 04 90 01 2c 01 00 00 00 ff ff ff 0c 00"))

    assert data is not None
    assert data.instantaneous_speed_kmh == 4.0
    assert data.total_distance_m == 300
    assert data.total_energy_kcal == 0
    assert data.elapsed_time_s == 12


def test_parse_treadmill_data_with_calories() -> None:
    data = parse_treadmill_data(bytes.fromhex("84 04 58 02 16 00 00 01 00 ff ff ff 17 00"))

    assert data is not None
    assert data.instantaneous_speed_kmh == 6.0
    assert data.total_distance_m == 22
    assert data.total_energy_kcal == 1
    assert data.elapsed_time_s == 23
