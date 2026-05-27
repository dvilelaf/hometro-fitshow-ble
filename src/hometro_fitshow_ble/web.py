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

from .controller import TreadmillController

STATIC_DIR = Path(__file__).with_name("web_static")


class SpeedRequest(BaseModel):
    speed_kmh: Annotated[float, Field(ge=0, le=30)]


def create_app(address: str, *, timeout: float = 15.0) -> FastAPI:
    controller = TreadmillController(address, timeout=timeout)
    app = FastAPI(title="HomeTro FitShow BLE")
    app.state.controller = controller

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/state")
    async def state() -> dict:
        return controller.state.snapshot()

    @app.post("/api/connect")
    async def connect() -> dict:
        return await _call(controller.connect)

    @app.post("/api/disconnect")
    async def disconnect() -> dict:
        return await _call(lambda: controller.disconnect(stop_first=True))

    @app.post("/api/control/request")
    async def request_control() -> dict:
        return await _call(controller.request_control)

    @app.post("/api/control/start")
    async def start(request: SpeedRequest) -> dict:
        return await _call(lambda: controller.start(request.speed_kmh))

    @app.post("/api/control/stop")
    async def stop() -> dict:
        return await _call(controller.stop)

    @app.post("/api/control/pause")
    async def pause() -> dict:
        return await _call(controller.pause)

    @app.post("/api/control/resume")
    async def resume() -> dict:
        return await _call(controller.resume)

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


def run_server(address: str, *, host: str, port: int, timeout: float = 15.0) -> None:
    app = create_app(address, timeout=timeout)
    uvicorn.run(app, host=host, port=port)
