from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ble_ops import scan_devices
from .controller import TreadmillController

STATIC_DIR = Path(__file__).with_name("web_static")


class SpeedRequest(BaseModel):
    speed_kmh: Annotated[float, Field(ge=0, le=30)]


class ConnectRequest(BaseModel):
    address: str


def create_app(address: str = "", *, timeout: float = 15.0) -> FastAPI:
    controller = TreadmillController(address, timeout=timeout)
    app = FastAPI(title="HomeTro FitShow BLE")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def post(path, operation) -> None:
        async def endpoint() -> dict:
            return await _call(operation)

        app.add_api_route(path, endpoint, methods=["POST"])

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/state")
    async def state() -> dict:
        return controller.state.snapshot()

    @app.get("/api/devices/scan")
    async def scan(timeout_s: float = 5.0, contains: str | None = None) -> list[dict]:
        rows = await scan_devices(timeout=timeout_s, contains=contains)
        return [row.to_json() for row in rows if row.is_known_treadmill()]

    @app.post("/api/connect")
    async def connect(request: ConnectRequest) -> dict:
        return await _call(lambda: controller.connect_to(request.address))

    post("/api/disconnect", lambda: controller.disconnect(stop_first=True))
    post("/api/connection-toggle", controller.connection_toggle)
    post("/api/control/play", controller.play)
    post("/api/control/primary", controller.primary_action)
    post("/api/control/stop", controller.stop)
    post("/api/control/pause-toggle", controller.pause_toggle)

    @app.post("/api/control/speed")
    async def speed(request: SpeedRequest) -> dict:
        return await _call(lambda: controller.set_speed(request.speed_kmh))

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(_event_stream(controller), media_type="text/event-stream")

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await controller.disconnect(stop_first=True)

    return app


async def _call(operation) -> dict:
    try:
        return await operation()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _event_stream(controller: TreadmillController) -> AsyncIterator[str]:
    queue = await controller.subscribe()
    try:
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=15)
                yield f"data: {json.dumps(payload)}\n\n"
            except TimeoutError:
                yield ": keepalive\n\n"
    finally:
        controller.unsubscribe(queue)


def run_server(address: str = "", *, host: str, port: int, timeout: float = 15.0) -> None:
    app = create_app(address, timeout=timeout)
    uvicorn.run(app, host=host, port=port)
