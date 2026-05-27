from pathlib import Path

APP_JS = Path("src/hometro_fitshow_ble/web_static/app.js")


def app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def test_frontend_does_not_decide_control_actions_from_button_text() -> None:
    source = app_source()

    assert "textContent ===" not in source
    assert "textContent ==" not in source
    assert "textContent !==" not in source
    assert "textContent !=" not in source


def test_frontend_only_renders_pause_button_text_inside_render() -> None:
    source = app_source()
    render_start = source.index("function renderState")
    render_end = source.index("async function api")

    assignments = [
        line.strip()
        for line in source.splitlines()
        if "pauseButton.textContent =" in line
    ]
    render_block = source[render_start:render_end]

    assert assignments, "render should set the Pause/Resume label"
    assert all(assignment in render_block for assignment in assignments)


def test_frontend_uses_minimal_play_and_pause_toggle_endpoints() -> None:
    source = app_source()

    assert '"/api/control/play"' in source
    assert '"/api/control/pause-toggle"' in source
    assert '"/api/control/resume"' not in source
