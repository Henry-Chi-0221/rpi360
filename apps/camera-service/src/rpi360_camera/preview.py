"""One paired video track. No stitching or viewpoint rendering on the Pi."""

import asyncio
import json
import time
from fractions import Fraction

import av
from aiortc import MediaStreamTrack
from aiortc.mediastreams import MediaStreamError

from .capture import packed_yuv


class PairedPreview(MediaStreamTrack):
    kind = "video"

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.sequence = 0
        self.origin_ns = None
        self.last_send = 0.0
        self.channel = None
        self.codec = None
        self.sent = 0
        self.encode_seconds = 0.0
        engine.preview_enabled = True

    async def recv(self):
        while self.readyState == "live":
            pair = await asyncio.to_thread(self.engine.wait_pair, self.sequence)
            if pair is None:
                continue
            self.sequence = pair.sequence
            now = pair.first.sensor_ns / 1_000_000_000
            if now - self.last_send < 0.95 / self.engine.preview_fps:
                continue
            self.last_send = now
            if self.origin_ns is None:
                self.origin_ns = pair.first.sensor_ns
            image = packed_yuv(pair)
            frame = av.VideoFrame.from_ndarray(image, format="yuv420p")
            # H.264 level 3.1 interoperable frame budget: 1640x616 exceeds
            # 3600 macroblocks. Scale both complete lenses, never crop their FOV.
            frame = frame.reformat(width=1440, height=540, format="yuv420p")
            frame.pts = (
                (pair.first.sensor_ns - self.origin_ns) * 90_000 // 1_000_000_000
            )
            frame.time_base = Fraction(1, 90_000)
            if self.codec is None:
                self.codec = av.CodecContext.create("libx264", "w")
                self.codec.width, self.codec.height = frame.width, frame.height
                self.codec.pix_fmt = "yuv420p"
                self.codec.time_base = frame.time_base
                self.codec.framerate = Fraction(self.engine.fps)
                self.codec.bit_rate = 4_000_000
                self.codec.gop_size = self.engine.fps
                self.codec.thread_count = 1
                self.codec.options = {
                    "preset": "ultrafast",
                    "tune": "zerolatency",
                    "profile": "baseline",
                    "level": "3.1",
                }
            before = time.monotonic()
            packets = await asyncio.to_thread(self.codec.encode, frame)
            cost = time.monotonic() - before
            self.encode_seconds += cost
            self.sent += 1
            if self.sent >= 30 and self.encode_seconds / self.sent > 0.025:
                self.engine.preview_fps = 15
            if (
                self.channel
                and self.channel.readyState == "open"
                and self.channel.bufferedAmount < 65536
            ):
                self.channel.send(
                    json.dumps(
                        {
                            "pair_id": pair.sequence,
                            "layout": "side-by-side",
                            "calibration_id": (self.engine.calibration or {}).get("id"),
                            "sync_locked": self.engine.pairer.locked,
                            "pts90k": frame.pts,
                            "sensor_ns": [
                                str(pair.first.sensor_ns),
                                str(pair.second.sensor_ns),
                            ],
                            "delta_us": pair.delta_ns / 1000,
                        }
                    )
                )
            if packets:
                return packets[0]
        raise MediaStreamError

    def stop(self):
        self.engine.preview_enabled = False
        super().stop()
