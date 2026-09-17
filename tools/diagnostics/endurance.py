"""Exercise real device recording and WebRTC together; emit observed evidence.

RPI360_TOKEN_FILE points to a private file containing a paired token.
This writes a new test recording; it never alters existing recordings.
"""

import argparse
import asyncio
import json
import os
import time
import uuid
from pathlib import Path

import httpx
from aiortc import (
    RTCConfiguration,
    RTCPeerConnection,
    RTCRtpReceiver,
    RTCSessionDescription,
)


async def run(args):
    token = Path(os.environ["RPI360_TOKEN_FILE"]).read_text().strip()
    client = httpx.AsyncClient(
        base_url=args.url, headers={"Authorization": "Bearer " + token}, timeout=30
    )

    async def request(path, body=None):
        r = await (client.get(path) if body is None else client.post(path, json=body))
        r.raise_for_status()
        return r.json()

    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    transceiver = pc.addTransceiver("video", direction="recvonly")
    transceiver.setCodecPreferences(
        [
            c
            for c in RTCRtpReceiver.getCapabilities("video").codecs
            if c.mimeType.lower() == "video/h264"
        ]
    )
    channel = pc.createDataChannel("frames", ordered=False, maxRetransmits=0)
    samples = []
    received = 0
    first_pts = None
    last_pts = None
    metadata = 0
    task = None

    @channel.on("message")
    def message(data):
        nonlocal metadata
        metadata += 1

    @pc.on("track")
    def track(track):
        nonlocal task

        async def consume():
            nonlocal received, first_pts, last_pts
            while True:
                frame = await track.recv()
                if first_pts is None:
                    first_pts = frame.pts * frame.time_base
                last_pts = frame.pts * frame.time_base
                received += 1

        task = asyncio.create_task(consume())

    recording = None
    session = None
    try:
        await request("/v1/capture/start", {})
        for _ in range(30):
            if (await request("/v1/status"))["sync"]["locked"]:
                break
            await asyncio.sleep(1)
        recording = await request(
            "/v1/recordings/start", {"request_id": uuid.uuid4().hex}
        )
        await pc.setLocalDescription(await pc.createOffer())
        session = await request(
            "/v1/preview-sessions",
            {"type": pc.localDescription.type, "sdp": pc.localDescription.sdp},
        )
        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=session["sdp"], type=session["type"])
        )
        start = time.monotonic()
        while time.monotonic() - start < args.seconds:
            await asyncio.sleep(min(10, args.seconds))
            status = await request("/v1/status")
            sample = {
                "elapsed_s": time.monotonic() - start,
                "preview_received": received,
                "status": status,
            }
            samples.append(sample)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps({"state": "running", "samples": samples}, indent=2)
            )
            if task and task.done():
                task.result()
            if status["error"] or status["recording"]["error"]:
                raise RuntimeError(status)
            print(json.dumps(sample), flush=True)
        recording = await request(
            "/v1/recordings/stop", {"request_id": uuid.uuid4().hex}
        )
        result = {
            "state": "finished",
            "seconds": time.monotonic() - start,
            "recording": recording,
            "preview_received": received,
            "preview_media_duration_s": float(last_pts - first_pts)
            if first_pts is not None
            else 0,
            "metadata_received": metadata,
            "samples": samples,
            "limitations": [
                "Does not measure glass-to-glass latency or browser rendering.",
                "Frame retention requires separate sensor/index analysis.",
            ],
        }
        args.output.write_text(json.dumps(result, indent=2))
    finally:
        if task:
            task.cancel()
        await pc.close()
        if session:
            await client.delete("/v1/preview-sessions/" + session["id"])
        if recording and recording.get("state") == "recording":
            await request("/v1/recordings/stop", {"request_id": uuid.uuid4().hex})
        await client.aclose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8765")
    p.add_argument("--seconds", type=int, default=3600)
    p.add_argument("--output", type=Path, required=True)
    asyncio.run(run(p.parse_args()))
