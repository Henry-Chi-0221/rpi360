"""Single owner of both sensors; preview backpressure never owns recording."""

import collections
import fcntl
import json
import queue
import threading
from fractions import Fraction
from pathlib import Path

import numpy as np

from .recording import BundleRecorder
from .settings import CameraSettings
from .storage import RecordingStore, atomic_json
from .synchronization import Pairer, SensorFrame


def unpack_yuv(buffer, width, height, stride):
    """Strip ISP row padding without cropping the physical camera view."""
    data = np.asarray(buffer, dtype=np.uint8).reshape(-1)
    y_size = stride * height
    chroma_size = y_size // 4
    return (
        data[:y_size].reshape(height, stride)[:, :width].copy(),
        data[y_size : y_size + chroma_size]
        .reshape(height // 2, stride // 2)[:, : width // 2]
        .copy(),
        data[y_size + chroma_size : y_size + 2 * chroma_size]
        .reshape(height // 2, stride // 2)[:, : width // 2]
        .copy(),
    )


def packed_yuv(pair):
    planes = [
        np.concatenate((a, b), axis=1)
        for a, b in zip(pair.first.planes, pair.second.planes, strict=False)
    ]
    h, w = planes[0].shape
    return np.concatenate([p.reshape(-1) for p in planes]).reshape(h * 3 // 2, w)


class CaptureEngine:
    record_size = (1640, 1232)
    preview_size = (820, 616)
    fps = 30

    def __init__(self, data_dir, calibration=None):
        self.root = Path(data_dir).resolve()
        self.store = RecordingStore(self.root / "recordings")
        self.calibration = calibration
        self.settings_path = self.root / "settings.json"
        self.settings = (
            CameraSettings.model_validate_json(self.settings_path.read_text())
            if self.settings_path.exists()
            else CameraSettings(revision=1)
        )
        self.condition = threading.Condition()
        self.lifecycle = threading.RLock()
        self.pairer = Pairer()
        self.latest = None
        self.cameras = []
        self.encoders = []
        self.recorder = None
        self.record_queue = None
        self.record_thread = None
        self.record_queue_peak = 0
        self.last_recording = None
        self.owner_lock = None
        self.received = [0, 0]
        self.metadata = [collections.OrderedDict(), collections.OrderedDict()]
        self.preview_enabled = False
        self.preview_fps = 30
        self.error = None
        self.clock_epoch = (
            Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            if Path("/proc/sys/kernel/random/boot_id").exists()
            else "unsupported-host"
        )

    @property
    def running(self):
        return bool(self.cameras)

    def start(self):
        with self.lifecycle:
            if self.running:
                return
            from libcamera import controls
            from picamera2 import Picamera2

            self.owner_lock = (self.root / "camera.lock").open("a")
            try:
                fcntl.flock(self.owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.pairer = Pairer()
                self.latest = None
                self.error = None
                for i in (0, 1):
                    c = Picamera2(i)
                    self.cameras.append(c)
                    cfg = c.create_video_configuration(
                        main={"size": self.record_size, "format": "YUV420"},
                        lores={"size": self.preview_size, "format": "YUV420"},
                        sensor={"output_size": self.record_size, "bit_depth": 10},
                        controls={"FrameRate": self.fps},
                        buffer_count=8,
                    )
                    c.configure(cfg)
                    c.set_controls(self.settings.controls())
                    c.set_controls(
                        {
                            "SyncMode": controls.rpi.SyncModeEnum.Server
                            if i == 0
                            else controls.rpi.SyncModeEnum.Client,
                            "SyncFrames": 100,
                        }
                    )
                    stride = c.camera_configuration()["lores"]["stride"]
                    c.pre_callback = self._callback(i, stride)
                self.cameras[1].start()
                self.cameras[0].start()
            except BaseException:
                self.close()
                raise

    def update_settings(self, value):
        with self.lifecycle:
            if value.revision != self.settings.revision:
                raise ValueError("settings revision changed; read the latest settings")
            previous = self.settings
            updated = value.model_copy(update={"revision": value.revision + 1})
            try:
                for camera in self.cameras:
                    camera.set_controls(updated.controls())
                atomic_json(self.settings_path, updated.model_dump(mode="json"))
            except Exception:
                for camera in self.cameras:
                    camera.set_controls(previous.controls())
                raise
            self.settings = updated
            return updated.model_dump(mode="json")

    def _callback(self, i, stride):
        def receive(request):
            try:
                md = request.get_metadata()
                ns = int(md["SensorTimestamp"])
                self.received[i] += 1
                seq = int(getattr(request.request, "sequence", self.received[i]))
                with self.condition:
                    record_metadata = {
                        "sensor_ns": str(ns),
                        "sequence": seq,
                        "exposure_us": int(md.get("ExposureTime", 0)),
                        "frame_duration_us": int(md.get("FrameDuration", 0)),
                        "sync_ready": bool(md.get("SyncReady", False)),
                        "sync_locked": self.pairer.locked,
                        "scaler_crop": list(md.get("ScalerCrop", ())),
                    }
                    self.metadata[i][ns // 1000] = record_metadata
                    while len(self.metadata[i]) > 120:
                        self.metadata[i].popitem(last=False)
                # The two sensors are paired before any preview rate reduction.
                planes = (
                    unpack_yuv(request.make_buffer("lores"), *self.preview_size, stride)
                    if self.preview_enabled
                    else None
                )
                frame = SensorFrame(
                    i,
                    seq,
                    ns,
                    record_metadata["exposure_us"],
                    record_metadata["frame_duration_us"],
                    record_metadata["sync_ready"],
                    planes,
                )
                with self.condition:
                    pair = self.pairer.push(frame)
                    if pair is not None:
                        self.latest = pair
                        self.condition.notify_all()
            except Exception as exc:
                with self.condition:
                    self.error = str(exc)
                    self.condition.notify_all()

        return receive

    def wait_pair(self, after=0, timeout=0.25):
        with self.condition:
            self.condition.wait_for(
                lambda: (
                    self.error
                    or not self.running
                    or (
                        self.latest
                        and self.latest.sequence > after
                        and self.latest.first.planes is not None
                        and self.latest.second.planes is not None
                    )
                ),
                timeout,
            )
            if self.error:
                raise RuntimeError(self.error)
            if (
                self.pairer.locked
                and self.latest
                and self.latest.sequence > after
                and self.latest.first.planes is not None
                and self.latest.second.planes is not None
            ):
                return self.latest
            return None

    def start_recording(self):
        with self.lifecycle:
            self.start()
            if self.recorder:
                return self.recorder.manifest
            with self.condition:
                if not self.pairer.locked:
                    raise RuntimeError(
                        "cameras are synchronizing; retry when sync.locked is true"
                    )
            from picamera2.encoders import H264Encoder
            from picamera2.outputs import Output

            recorder = BundleRecorder(
                self.store,
                self.calibration,
                self.record_size,
                self.fps,
                self.latest.first.sensor_ns,
                self.clock_epoch,
            )
            engine = self

            class SensorOutput(Output):
                def __init__(self, index, encoder):
                    super().__init__()
                    self.index = index
                    self.encoder = encoder

                def outputframe(
                    self, frame, keyframe=True, timestamp=None, packet=None, audio=False
                ):
                    if (
                        audio
                        or timestamp is None
                        or self.encoder.firsttimestamp is None
                    ):
                        return
                    sensor_us = int(self.encoder.firsttimestamp) + int(timestamp)
                    with engine.condition:
                        md = dict(engine.metadata[self.index].get(sensor_us, {}))
                    if not md:
                        md = {"metadata_missing": True}
                    if recorder.error:
                        return
                    try:
                        engine.record_queue.put_nowait(
                            (self.index, bytes(frame), sensor_us, keyframe, md)
                        )
                        engine.record_queue_peak = max(
                            engine.record_queue_peak, engine.record_queue.qsize()
                        )
                    except queue.Full:
                        recorder.error = (
                            "recording storage queue exhausted; recording stopped "
                            "without changing source timing"
                        )
                        threading.Thread(
                            target=engine.stop_recording,
                            name="recording-fault",
                            daemon=True,
                        ).start()

            self.recorder = recorder
            self.record_queue = queue.Queue(maxsize=90)
            self.record_queue_peak = 0

            fault_notified = threading.Event()

            def write_packets():
                while True:
                    item = self.record_queue.get()
                    try:
                        if item is None:
                            return
                        recorder.write(*item)
                        if recorder.error and not fault_notified.is_set():
                            fault_notified.set()
                            # Stop encoders outside the writer: stop_recording joins us.
                            threading.Thread(
                                target=engine.stop_recording,
                                name="recording-fault",
                                daemon=True,
                            ).start()
                    except Exception as exc:
                        recorder.error = str(exc)
                        threading.Thread(
                            target=engine.stop_recording,
                            name="recording-fault",
                            daemon=True,
                        ).start()
                    finally:
                        self.record_queue.task_done()

            self.record_thread = threading.Thread(
                target=write_packets, name="recording-storage", daemon=True
            )
            self.record_thread.start()
            try:
                for i, camera in enumerate(self.cameras):
                    encoder = H264Encoder(
                        bitrate=8_000_000,
                        framerate=Fraction(self.fps),
                        iperiod=self.fps,
                        repeat=True,
                    )
                    encoder.preset = "ultrafast"
                    encoder.threads = 1
                    self.encoders.append(encoder)
                    camera.start_encoder(encoder, SensorOutput(i, encoder), name="main")
            except BaseException as exc:
                recorder.error = str(exc)
                self.stop_recording()
                raise
            return recorder.manifest

    def stop_recording(self):
        with self.lifecycle:
            if not self.recorder:
                return self.last_recording
            recorder = self.recorder
            for camera, encoder in zip(self.cameras, self.encoders, strict=False):
                try:
                    camera.stop_encoder(encoder)
                except Exception as exc:
                    recorder.error = str(exc)
            self.encoders = []
            if self.record_thread:
                self.record_queue.put(None)
                self.record_thread.join()
                self.record_thread = None
                self.record_queue = None
            try:
                self.last_recording = recorder.close()
            finally:
                self.recorder = None
            return self.last_recording

    def status(self):
        with self.condition:
            return {
                "running": self.running,
                "error": self.error,
                "sync": self.pairer.status(),
                "sensor_frames": list(self.received),
                "preview_fps": self.preview_fps,
                "recording_queue_peak": self.record_queue_peak,
                "recording": (
                    {
                        "id": self.recorder.id,
                        "frames": list(self.recorder.counts),
                        "error": self.recorder.error,
                    }
                    if self.recorder
                    else None
                ),
            }

    def close(self):
        with self.lifecycle:
            errors = []
            try:
                self.stop_recording()
            except Exception as exc:
                errors.append(exc)
            for camera in self.cameras:
                for operation in (camera.stop, camera.close):
                    try:
                        operation()
                    except Exception as exc:
                        errors.append(exc)
            self.cameras = []
            self.preview_enabled = False
            if self.owner_lock:
                try:
                    self.owner_lock.close()
                except Exception as exc:
                    errors.append(exc)
                finally:
                    self.owner_lock = None
            with self.condition:
                self.condition.notify_all()
            if errors:
                raise ExceptionGroup("Camera shutdown encountered errors", errors)


def load_calibration(path):
    if not path:
        return None
    value = json.loads(Path(path).read_text())
    if value.get("schema_version") not in (1, 2):
        raise ValueError("unsupported calibration version")
    return value
