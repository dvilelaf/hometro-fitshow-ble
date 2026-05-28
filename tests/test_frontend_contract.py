import re
from pathlib import Path

APP_JS = Path("src/hometro_fitshow_ble/web_static/app.js")
INDEX_HTML = Path("src/hometro_fitshow_ble/web_static/index.html")


def app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def index_source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


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
    assert '"/api/connection-toggle"' in source


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
