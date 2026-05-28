set shell := ["bash", "-uc"]

host := env_var_or_default("HOMETRO_HOST", "127.0.0.1")
port := env_var_or_default("HOMETRO_PORT", "8000")
pidfile := env_var_or_default("HOMETRO_PIDFILE", ".hometro-server.pid")
logfile := env_var_or_default("HOMETRO_LOGFILE", ".hometro-server.log")

default:
    @just --list

_setup:
    @command -v uv >/dev/null || { echo "uv is required. Install it first: https://docs.astral.sh/uv/"; exit 1; }
    @if [ ! -x .venv/bin/python ]; then uv venv .venv; fi
    @uv pip install -q -e ".[dev]"

run: _setup
    @if [ -f "{{pidfile}}" ] && kill -0 "$(< "{{pidfile}}")" 2>/dev/null; then \
        echo "Server already running with PID $(< "{{pidfile}}")"; \
        echo "http://{{host}}:{{port}}"; \
        exit 0; \
    fi; \
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq '(^|:){{port}}$'; then \
        echo "Port {{port}} is already in use. Run just stop or set HOMETRO_PORT."; \
        exit 1; \
    fi; \
    nohup env PYTHONPATH=src .venv/bin/python -m hometro_fitshow_ble.cli web --host "{{host}}" --port "{{port}}" > "{{logfile}}" 2>&1 < /dev/null & \
    echo "$!" > "{{pidfile}}"; \
    echo "Server started with PID $(< "{{pidfile}}")"; \
    echo "http://{{host}}:{{port}}"

stop:
    @if [ ! -f "{{pidfile}}" ]; then \
        echo "No pidfile at {{pidfile}}"; \
        exit 0; \
    fi; \
    pid="$(< "{{pidfile}}")"; \
    if ! kill -0 "$pid" 2>/dev/null; then \
        rm -f "{{pidfile}}"; \
        echo "Stale pidfile removed"; \
        exit 0; \
    fi; \
    kill "$pid" 2>/dev/null || true; \
    for _ in 1 2 3 4 5; do \
        if kill -0 "$pid" 2>/dev/null; then sleep 0.2; else break; fi; \
    done; \
    if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null || true; fi; \
    rm -f "{{pidfile}}"; \
    echo "Server stopped"
