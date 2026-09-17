"""Verify direct Pi HTTPS signaling and decoded WebRTC frames without recording.

This verifies the network/media path, not Safari rendering or display latency.
Requires httpx and aiortc (available in the repository's development environment).
"""

import argparse
import asyncio
import contextlib
import json
import ssl
import time
from pathlib import Path

import httpx
from aiortc import (
    RTCConfiguration,
    RTCPeerConnection,
    RTCRtpReceiver,
    RTCSessionDescription,
)


async def check(args):
    context = ssl.create_default_context(cafile=str(args.ca))
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
    frames, diagnostics, dimensions, times = 0, 0, set(), []
    task, session = None, None

    @channel.on("message")
    def message(_):
        nonlocal diagnostics
        diagnostics += 1

    @pc.on("track")
    def track(track):
        nonlocal task

        async def consume():
            nonlocal frames
            while True:
                frame = await track.recv()
                dimensions.add((frame.width, frame.height))
                times.append(float(frame.pts * frame.time_base))
                frames += 1

        task = asyncio.create_task(consume())

    async with httpx.AsyncClient(
        base_url=args.url, verify=context, timeout=30
    ) as client:
        try:
            response = await client.get("/v1/capabilities")
            response.raise_for_status()
            capabilities = response.json()
            await pc.setLocalDescription(await pc.createOffer())
            response = await client.post(
                "/v1/preview-sessions",
                json={
                    "type": pc.localDescription.type,
                    "sdp": pc.localDescription.sdp,
                },
            )
            response.raise_for_status()
            session = response.json()
            await pc.setRemoteDescription(
                RTCSessionDescription(
                    sdp=session["sdp"],
                    type=session["type"],
                )
            )
            start = time.monotonic()
            while time.monotonic() - start < args.seconds:
                await asyncio.sleep(0.25)
                if task and task.done():
                    task.result()
            status = (await client.get("/v1/status")).json()
            assert frames >= 2, "No decoded moving preview received"
            assert dimensions == {tuple(capabilities["preview"]["size"])}, dimensions
            assert all(b > a for a, b in zip(times, times[1:], strict=False)), (
                "Non-monotonic video PTS"
            )
            result = {
                "url": args.url,
                "tls_verified": True,
                "seconds": args.seconds,
                "frames_decoded": frames,
                "dimensions": sorted(dimensions),
                "diagnostics_received": diagnostics,
                "status": status,
                "scope": "Direct Pi HTTPS and H.264 WebRTC; not an iPad Safari test",
            }
            print(json.dumps(result, indent=2))
            if args.output:
                args.output.write_text(json.dumps(result, indent=2) + "\n")
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await pc.close()
            if session:
                await client.delete("/v1/preview-sessions/" + session["id"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--output", type=Path)
    asyncio.run(check(parser.parse_args()))
