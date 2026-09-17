"""Fragmented MP4 sources with explicit sensor-to-media time mapping."""

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from fractions import Fraction

import av

from .storage import atomic_json, file_info


class BundleRecorder:
    def __init__(self, store, calibration, size, fps, epoch_ns, clock_epoch):
        store.require_space()
        self.store = store
        self.id = uuid.uuid4().hex
        self.path = store.directory(self.id)
        self.path.mkdir()
        self.epoch_us = epoch_ns // 1000
        self.lock = threading.RLock()
        self.error = None
        self.closed = False
        self.containers = [None, None]
        self.handles = [None, None]
        self.streams = [None, None]
        self.counts = [0, 0]
        self.last_pts = [None, None]
        self.first_pts = [None, None]
        self.last_sync = [0.0, 0.0]
        self.indices = [None, None]
        self.manifest = {
            "schema_version": 2,
            "id": self.id,
            "state": "recording",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "clock": {
                "epoch": clock_epoch,
                "origin_sensor_ns": str(epoch_ns),
                "unit": "microseconds",
            },
            "streams": [
                {
                    "camera": i,
                    "path": f"camera{i}.mp4",
                    "width": size[0],
                    "height": size[1],
                    "nominal_fps": fps,
                    "codec": "h264",
                    "frames": 0,
                }
                for i in (0, 1)
            ],
            "calibration": "calibration.json" if calibration else None,
            "sync": {"method": "libcamera-software", "tolerance_us": 1000},
            "files": [],
        }
        if calibration:
            atomic_json(self.path / "calibration.json", calibration)
        atomic_json(self.path / "manifest.json", self.manifest)
        try:
            for i in (0, 1):
                self.handles[i] = (self.path / f"camera{i}.mp4").open("wb")
                self.containers[i] = av.open(
                    self.handles[i],
                    "w",
                    format="mp4",
                    options={
                        "movflags": "frag_keyframe+empty_moov+default_base_moof",
                        "frag_duration": "1000000",
                        "flush_packets": "1",
                    },
                )
                self.streams[i] = self.containers[i].add_stream(
                    "h264", rate=Fraction(fps)
                )
                self.streams[i].width, self.streams[i].height = size
                self.streams[i].pix_fmt = "yuv420p"
                self.streams[i].time_base = Fraction(1, 1_000_000)
                self.indices[i] = (self.path / f"camera{i}.frames.jsonl").open("w")
        except BaseException as exc:
            self.error = str(exc)
            self.close()
            raise

    def write(self, camera, data, sensor_us, keyframe, metadata):
        with self.lock:
            if self.closed or self.error:
                return
            try:
                pts = int(sensor_us) - self.epoch_us
                if pts < 0 or (
                    self.last_pts[camera] is not None and pts <= self.last_pts[camera]
                ):
                    raise ValueError(
                        "non-monotonic sensor timestamp; source recording stopped"
                    )
                packet = av.Packet(data)
                if self.first_pts[camera] is None:
                    self.first_pts[camera] = pts
                    self.manifest["streams"][camera]["media_start_offset_us"] = pts
                    atomic_json(self.path / "manifest.json", self.manifest)
                media_pts = pts - self.first_pts[camera]
                packet.pts = packet.dts = media_pts
                packet.time_base = Fraction(1, 1_000_000)
                packet.is_keyframe = keyframe
                packet.stream = self.streams[camera]
                self.containers[camera].mux(packet)
                self.indices[camera].write(
                    json.dumps(
                        {
                            "pts_us": pts,
                            "media_pts_us": media_pts,
                            "sensor_ns": str(int(sensor_us) * 1000),
                            **metadata,
                        }
                    )
                    + "\n"
                )
                self.last_pts[camera] = pts
                self.counts[camera] += 1
                now = time.monotonic()
                if now - self.last_sync[camera] >= 1:
                    self.store.require_space()
                    self.indices[camera].flush()
                    os.fsync(self.indices[camera].fileno())
                    self.handles[camera].flush()
                    os.fsync(self.handles[camera].fileno())
                    self.last_sync[camera] = now
            except Exception as exc:
                self.error = str(exc)
                self.manifest["state"] = "recovery_required"
                self.manifest["error"] = self.error
                try:
                    atomic_json(self.path / "manifest.json", self.manifest)
                except OSError:
                    # A full disk must not kill the packet-draining worker.
                    # The previous journal still identifies an unfinished bundle.
                    pass

    def close(self):
        with self.lock:
            if self.closed:
                return self.manifest
            self.closed = True
            for i in (0, 1):
                try:
                    if self.containers[i]:
                        self.containers[i].close()
                except Exception as exc:
                    self.error = str(exc)
                for f in (self.indices[i], self.handles[i]):
                    if f and not f.closed:
                        try:
                            f.flush()
                            os.fsync(f.fileno())
                        except Exception as exc:
                            self.error = str(exc)
                        finally:
                            f.close()
                self.manifest["streams"][i]["frames"] = self.counts[i]
                self.manifest["streams"][i]["last_pts_us"] = self.last_pts[i]
            if not all(self.counts):
                self.error = self.error or "one or both camera tracks are empty"
            self.manifest["state"] = "recovery_required" if self.error else "complete"
            if self.error:
                self.manifest["error"] = self.error
            try:
                self.manifest["files"] = [
                    file_info(p)
                    for p in sorted(self.path.iterdir())
                    if p.is_file() and p.name != "manifest.json"
                ]
                atomic_json(self.path / "manifest.json", self.manifest)
            except OSError as exc:
                self.error = str(exc)
                self.manifest["state"] = "recovery_required"
                self.manifest["error"] = self.error
                try:
                    atomic_json(self.path / "manifest.json", self.manifest)
                except OSError:
                    pass
            return self.manifest
