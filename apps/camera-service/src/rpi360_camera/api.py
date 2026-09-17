"""Versioned device API; hardware is injected for contract tests."""

import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from aiortc import (
    RTCConfiguration,
    RTCPeerConnection,
    RTCRtpSender,
    RTCSessionDescription,
)
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .access import AccessPolicy
from .preview import PairedPreview
from .settings import CameraSettings
from .storage import atomic_json


class Command(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)


class Offer(BaseModel):
    sdp: str = Field(max_length=100000)
    type: Literal["offer"]


def create_app(engine, allowed_origins=(), web_root=None, *, api_token=None):
    access = AccessPolicy(api_token)
    connections = {}
    preview_lock = asyncio.Lock()
    command_lock = asyncio.Lock()
    watchdogs = set()
    ledger_path = engine.root / "commands.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}

    @asynccontextmanager
    async def lifespan(app):
        yield
        for task in watchdogs:
            task.cancel()
        await asyncio.gather(*watchdogs, return_exceptions=True)
        await asyncio.gather(*(pc.close() for pc, _ in list(connections.values())))
        await asyncio.to_thread(engine.close)

    app = FastAPI(title="RPI360 Device API", version="2.0.0-alpha.1", lifespan=lifespan)
    app.state.engine = engine
    app.state.access = access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Range"],
        expose_headers=["Content-Range", "ETag", "Accept-Ranges"],
    )

    @app.middleware("http")
    async def check_origin(request, call_next):
        from fastapi.responses import JSONResponse

        if access.mode == "local" and not access.local_request(request):
            return JSONResponse(
                {"detail": "local access requires loopback and localhost Host"},
                status_code=403,
            )
        origin = request.headers.get("origin")
        same_origin = origin == str(request.base_url).rstrip("/")
        if (origin and not same_origin and origin not in allowed_origins) or (
            not origin and request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse({"detail": "origin is not allowed"}, status_code=403)
        return await call_next(request)

    def authenticated(request: Request):
        return access.verify(request)

    protected = [Depends(authenticated)]

    @app.get("/v1/info")
    def info():
        return {
            "name": "RPI360",
            "api_version": 1,
            "version": "2.0.0-alpha.1",
            "access_mode": access.mode,
        }

    @app.get("/v1/capabilities", dependencies=protected)
    def capabilities():
        return {
            "api_version": 1,
            "revision": 1,
            "recording_schema": 2,
            "calibration_schema": [1, 2],
            "access_mode": access.mode,
            "control_policy": "shared",
            "preview_clients": 1,
            "recording_profiles": [
                {
                    "id": "balanced",
                    "width": 1640,
                    "height": 1232,
                    "fps": 30,
                    "bitrate_per_camera": 8_000_000,
                    "validation": "candidate",
                }
            ],
            "preview": {
                "transport": "webrtc",
                "codec": "H264",
                "layout": "side-by-side",
                "camera_rects": [[0, 0, 720, 540], [720, 0, 720, 540]],
                "size": [1440, 540],
                "fps": 30,
                "bitrate": 4_000_000,
            },
        }

    @app.get("/v1/status", dependencies=protected)
    def status():
        return engine.status()

    @app.get("/v1/settings", dependencies=protected)
    def settings():
        return engine.settings.model_dump(mode="json")

    @app.put("/v1/settings", dependencies=protected)
    async def update_settings(body: CameraSettings):
        async with command_lock:
            try:
                return await asyncio.to_thread(engine.update_settings, body)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc

    @app.get("/v1/calibration", dependencies=protected)
    def calibration():
        return {"revision": 1, "profile": engine.calibration}

    @app.post("/v1/capture/start", dependencies=protected)
    async def start_capture():
        try:
            await asyncio.to_thread(engine.start)
            return engine.status()
        except Exception as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/v1/capture/stop", dependencies=protected)
    async def stop_capture():
        async with command_lock:
            if connections or engine.status().get("recording"):
                raise HTTPException(
                    409, "stop recording and preview before closing capture"
                )
            await asyncio.to_thread(engine.close)
            return engine.status()

    async def command(operation, body, function):
        async with command_lock:
            key = operation + ":" + body.request_id
            if key in ledger:
                return ledger[key]
            try:
                result = await asyncio.to_thread(function)
            except (RuntimeError, OSError) as exc:
                raise HTTPException(409, str(exc)) from exc
            ledger[key] = result
            while len(ledger) > 256:
                del ledger[next(iter(ledger))]
            atomic_json(ledger_path, ledger)
            return result

    @app.post("/v1/recordings/start", dependencies=protected)
    async def start_recording(body: Command):
        return await command("start", body, engine.start_recording)

    @app.post("/v1/recordings/stop", dependencies=protected)
    async def stop_recording(body: Command):
        return await command("stop", body, engine.stop_recording)

    @app.get("/v1/recordings", dependencies=protected)
    def recordings():
        return {"items": engine.store.recordings()}

    @app.get("/v1/recordings/{recording_id}", dependencies=protected)
    def manifest(recording_id: str):
        try:
            return engine.store.manifest(recording_id)
        except (ValueError, OSError) as exc:
            raise HTTPException(404, "recording not found") from exc

    @app.get("/v1/recordings/{recording_id}/files/{name}", dependencies=protected)
    def download(recording_id: str, name: str):
        try:
            path = engine.store.file(recording_id, name)
            entry = next(
                (
                    f
                    for f in engine.store.manifest(recording_id)["files"]
                    if f["path"] == name
                ),
                None,
            )
            headers = {"ETag": '"' + entry["sha256"] + '"'} if entry else {}
            return FileResponse(path, headers=headers, filename=name)
        except (ValueError, OSError) as exc:
            raise HTTPException(404, "recording file not found") from exc

    @app.post("/v1/preview-sessions", dependencies=protected)
    async def preview(body: Offer):
        async with preview_lock:
            if connections:
                raise HTTPException(409, "preview capacity reached (one viewer)")
            await asyncio.to_thread(engine.start)
            pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
            track = PairedPreview(engine)
            session_id = secrets.token_hex(16)
            connections[session_id] = (pc, track)

            async def expire_unconnected():
                # A lost answer or abandoned offer must not reserve capacity forever.
                await asyncio.sleep(30)
                if pc.connectionState != "connected":
                    connections.pop(session_id, None)
                    track.stop()
                    await pc.close()

            watchdog = asyncio.create_task(expire_unconnected())
            watchdogs.add(watchdog)
            watchdog.add_done_callback(watchdogs.discard)

            @pc.on("datachannel")
            def channel(channel):
                if channel.label == "frames":
                    track.channel = channel

            @pc.on("connectionstatechange")
            async def changed():
                if pc.connectionState in ("failed", "closed"):
                    connections.pop(session_id, None)
                    track.stop()
                    if pc.connectionState != "closed":
                        await pc.close()

            try:
                # aiortc resolves codecs while setting the remote description.
                # Set preferences first or an H.264 packet can be labelled as VP8.
                sender = pc.addTrack(track)
                transceiver = next(
                    t for t in pc.getTransceivers() if t.sender == sender
                )
                transceiver.setCodecPreferences(
                    [
                        c
                        for c in RTCRtpSender.getCapabilities("video").codecs
                        if c.mimeType.lower() == "video/h264"
                    ]
                )
                await pc.setRemoteDescription(
                    RTCSessionDescription(body.sdp, body.type)
                )
                await pc.setLocalDescription(await pc.createAnswer())
                return {
                    "id": session_id,
                    "type": pc.localDescription.type,
                    "sdp": pc.localDescription.sdp,
                }
            except BaseException:
                connections.pop(session_id, None)
                track.stop()
                await pc.close()
                raise

    @app.delete("/v1/preview-sessions/{session_id}", dependencies=protected)
    async def stop_preview(session_id: str):
        item = connections.pop(session_id, None)
        if item:
            pc, track = item
            track.stop()
            await pc.close()
        return {"closed": True}

    @app.get("/v1/events", dependencies=protected)
    async def events(request: Request):
        async def stream():
            previous = None
            while not await request.is_disconnected():
                current = json.dumps(engine.status())
                if current != previous:
                    yield "event: status\ndata: " + current + "\n\n"
                    previous = current
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream")

    if web_root:
        root = Path(web_root).resolve()
        if not (root / "index.html").is_file():
            raise ValueError("web root must contain a built workbench index.html")
        app.mount("/", StaticFiles(directory=root, html=True), name="workbench")
    return app
