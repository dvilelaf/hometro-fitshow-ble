import re
from pathlib import Path

APP_JS = Path("src/hometro_fitshow_ble/web_static/app.js")
INDEX_HTML = Path("src/hometro_fitshow_ble/web_static/index.html")
STYLES_CSS = Path("src/hometro_fitshow_ble/web_static/styles.css")


def app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def index_source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def styles_source() -> str:
    return STYLES_CSS.read_text(encoding="utf-8")


def find_matching_brace(source: str, open_brace: int) -> int:
    depth = 0
    for index in range(open_brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    raise AssertionError("unmatched function brace in app.js")


def function_ranges(source: str) -> list[tuple[str, int, int]]:
    ranges: list[tuple[str, int, int]] = []
    patterns = [
        re.compile(r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{"),
        re.compile(
            r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
            r"(?:async\s+)?function\s*\([^)]*\)\s*\{"
        ),
        re.compile(
            r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
            r"(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{"
        ),
    ]
    for pattern in patterns:
        for match in pattern.finditer(source):
            open_brace = source.index("{", match.start())
            close_brace = find_matching_brace(source, open_brace)
            ranges.append((match.group(1), open_brace, close_brace))
    return ranges


def enclosing_function(source: str, index: int) -> str | None:
    candidates = [
        (name, start, end)
        for name, start, end in function_ranges(source)
        if start <= index <= end
    ]
    if not candidates:
        return None
    name, _, _ = max(candidates, key=lambda candidate: candidate[1])
    return name


def start_button_text_occurrences(source: str) -> list[int]:
    return [match.start() for match in re.finditer(r"\bstartButton\.textContent\b", source)]


def test_frontend_does_not_read_primary_button_text_for_control_logic() -> None:
    source = app_source()

    for index in start_button_text_occurrences(source):
        after_property = source[index + len("startButton.textContent") :].lstrip()
        assert after_property.startswith("=")
        assert not after_property.startswith(("==", "==="))


def test_frontend_only_renders_primary_button_text_inside_render() -> None:
    source = app_source()
    assignments = list(re.finditer(r"\bstartButton\.textContent\s*=(?!=)", source))

    assert assignments, "render should set the Start/Pause/Resume label"
    for assignment in assignments:
        function_name = enclosing_function(source, assignment.start())
        assert function_name is not None
        assert "render" in function_name.lower()


def test_frontend_uses_backend_primary_control_endpoint() -> None:
    source = app_source()

    assert '"/api/control/primary"' in source
    assert '"/api/control/play"' not in source
    assert '"/api/control/pause-toggle"' not in source
    assert '"/api/control/resume"' not in source


def test_frontend_delegates_connection_and_pause_state_to_backend() -> None:
    source = app_source()

    assert "let state" not in source
    assert "pendingSpeedFlush" not in source
    assert "state?.connected" not in source
    assert '"/api/disconnect"' in source


def test_frontend_scans_and_connects_to_selected_device() -> None:
    source = app_source()
    html = index_source()

    assert "/api/devices/scan" in source
    assert '"/api/connect"' in source
    assert "device.address" in source
    assert 'id="scanButton"' in html
    assert 'id="devicePanel"' in html
    assert 'id="deviceList"' in html
    assert 'id="closeDevicePanelButton"' in html


def test_frontend_search_uses_device_panel_not_global_message() -> None:
    source = app_source()
    scan_index = source.index("async function scanDevices")
    scan_block = source[scan_index : source.index("\nels.scanButton", scan_index)]

    assert "els.devicePanel.hidden = false" in scan_block
    assert "No treadmill found" in source


def test_frontend_has_no_global_message_surface() -> None:
    source = app_source()
    html = index_source()
    styles = styles_source()

    assert "connectionMessage" not in source
    assert "connectionMessage" not in html
    assert "connection-message" not in styles
    assert "function message(" not in source
    assert "message(" not in source


def test_primary_controls_have_stable_dimensions() -> None:
    styles = styles_source()

    assert "grid-template-columns: repeat(2, 180px)" in styles
    assert ".buttons button" in styles
    assert "height: 44px" in styles
    assert "width: 100%" in styles


def test_frontend_renders_speed_chart_from_backend_history() -> None:
    source = app_source()
    html = index_source()
    styles = styles_source()

    assert 'id="speedChart"' in html
    assert "speedChartTitle" not in html
    assert "km/h over time" not in html
    assert "function drawSpeedChart(" in source
    assert "function drawSmoothPath(" in source
    assert "function timeStep(" in source
    assert "rgba(0, 216, 167, 0.18)" in source
    assert 'ctx.fillText("Speed"' in source
    assert "drawSpeedChart(state.speed_history || [])" in source
    assert ".speed-chart-panel" in styles
    assert "speed-chart-header" not in styles


def test_frontend_does_not_show_connected_address_as_global_message() -> None:
    source = app_source()

    assert "Connected to" not in source


def test_frontend_hides_raw_network_errors_from_user() -> None:
    source = app_source()

    assert "Cannot reach the local app" in source
    assert "NetworkError" not in source
    assert "error.message || String(error)" not in source


def test_frontend_has_notification_center() -> None:
    source = app_source()
    html = index_source()

    assert 'id="notificationButton"' in html
    assert 'id="notificationBadge"' in html
    assert 'id="notificationPanel"' in html
    assert 'id="notificationList"' in html
    assert 'id="clearNotificationsButton"' in html
    assert 'id="notificationToast"' in html
    assert "function notify(" in source
    assert "renderNotifications()" in source
    assert "userMessage(" in source


def test_notification_button_uses_local_icon_asset() -> None:
    styles = styles_source()
    icon_block = styles[styles.index(".notification-icon") : styles.index(".notification-badge")]

    assert "icons/bell.svg" in styles
    assert "::before" not in icon_block
    assert Path("src/hometro_fitshow_ble/web_static/icons/bell.svg").exists()


def test_eventsource_errors_are_user_notifications() -> None:
    source = app_source()

    assert "events.onerror = (error) => report(error);" in source
    assert "events.onerror = (error) => console.error(error);" not in source


def test_frontend_has_one_primary_control_button_and_stop() -> None:
    source = index_source()

    assert 'id="startButton"' in source
    assert 'id="stopButton"' in source
    assert 'id="pauseButton"' not in source


def test_space_key_uses_backend_primary_control() -> None:
    source = app_source()
    space_index = source.index('event.code === "Space"')
    block_end = source.index('} else if (/^[0-9]$/.test(event.key))', space_index)
    block = source[space_index:block_end]

    assert '"/api/control/primary"' in block
    assert '"/api/control/pause-toggle"' not in block
    assert '"/api/control/play"' not in block


def test_number_keys_set_speed_without_starting() -> None:
    source = app_source()
    set_speed_index = source.index("function setSpeed")
    set_speed_block = source[set_speed_index : source.index("async function flushSpeed")]
    digit_index = source.index('/^[0-9]$/.test(event.key)')
    digit_block = source[digit_index : source.index("}\n}, { capture: true });", digit_index)]

    assert '"/api/control/speed"' in set_speed_block
    assert "setSpeed(" in digit_block
    assert '"/api/control/primary"' not in digit_block
    assert '"/api/control/play"' not in digit_block
