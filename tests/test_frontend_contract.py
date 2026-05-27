import re
from pathlib import Path

APP_JS = Path("src/hometro_fitshow_ble/web_static/app.js")


def app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


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


def pause_button_text_occurrences(source: str) -> list[int]:
    return [match.start() for match in re.finditer(r"\bpauseButton\.textContent\b", source)]


def test_frontend_does_not_read_pause_button_text_for_control_logic() -> None:
    source = app_source()

    for index in pause_button_text_occurrences(source):
        after_property = source[index + len("pauseButton.textContent") :].lstrip()
        assert after_property.startswith("=")
        assert not after_property.startswith(("==", "==="))


def test_frontend_only_renders_pause_button_text_inside_render() -> None:
    source = app_source()
    assignments = list(re.finditer(r"\bpauseButton\.textContent\s*=(?!=)", source))

    assert assignments, "render should set the Pause/Resume label"
    for assignment in assignments:
        function_name = enclosing_function(source, assignment.start())
        assert function_name is not None
        assert "render" in function_name.lower()


def test_frontend_uses_minimal_play_and_pause_toggle_endpoints() -> None:
    source = app_source()

    assert '"/api/control/play"' in source
    assert '"/api/control/pause-toggle"' in source
    assert '"/api/control/resume"' not in source
