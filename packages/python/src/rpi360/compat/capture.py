"""v1 capture adapter delegating all hardware and recording to the v2 engine."""

import json
import time
import warnings
from pathlib import Path

from ..common.frames import FrameBundle
from ..common.metadata import calibration_profile_from_result, load_calibration_result
from ..rpi.recording import RecordingHandle, RecordingStatus, mux_recording


class ServiceLiveSource:
    kind = "live"
    supports_timeline = False

    def __init__(
        self,
        calibration_json,
        *,
        camera_indices=(0, 1),
        panorama_size=(2048, 1024),
        preview_size=None,
        record_size=None,
        fps=None,
        **kwargs,
    ):
        from rpi360_camera.capture import CaptureEngine

        warnings.warn(
            "Player.live is a diagnostic transition API; "
            "use the camera service and Device SDK for applications",
            DeprecationWarning,
            stacklevel=3,
        )
        if camera_indices != (0, 1):
            raise ValueError("v2 balanced capture uses camera indices 0 and 1")
        self._calibration_result = load_calibration_result(calibration_json)
        self._calibration = calibration_profile_from_result(self._calibration_result)
        self.panorama_size = panorama_size
        self.engine = CaptureEngine(
            Path.home() / ".local/share/rpi360", self._calibration_result
        )
        if record_size and tuple(record_size) != (1640, 1232):
            raise ValueError(
                "Only the full-field 1640x1232 recording profile is currently supported"
            )
        if fps is not None and float(fps) != 30:
            raise ValueError(
                "The balanced v2 profile requests 30 fps; "
                "source time is never reconstructed from this value"
            )
        self.sequence = 0
        self._handle = None
        self._output = None
        self._final = None
        self._overwrite = False

    @property
    def running(self):
        return self.engine.running

    @property
    def calibration(self):
        return self._calibration

    @property
    def calibration_result(self):
        return json.loads(json.dumps(self._calibration_result))

    @property
    def fps(self):
        return self.engine.fps

    @property
    def processing_sizes(self):
        return (self.engine.preview_size, self.engine.preview_size)

    def inspect(self):
        return {
            "source": "live",
            "fps": self.fps,
            "processing_sizes": self.processing_sizes,
            "panorama_size": self.panorama_size,
            "calibration_result": self.calibration_result,
            "capture": self.engine.status(),
        }

    def start(self):
        self.engine.start()
        self.engine.preview_enabled = True
        return self

    def read(self, timeout=0.03):
        import cv2
        import numpy as np

        pair = self.engine.wait_pair(self.sequence, timeout)
        if pair is None:
            return None
        self.sequence = pair.sequence
        w, h = self.engine.preview_size

        def image(frame):
            return cv2.cvtColor(
                np.concatenate([p.reshape(-1) for p in frame.planes]).reshape(
                    h * 3 // 2, w
                ),
                cv2.COLOR_YUV2BGR_I420,
            )

        return FrameBundle(
            image(pair.first),
            image(pair.second),
            self.calibration,
            index=pair.sequence,
            timestamp0=pair.first.sensor_ns / 1e9,
            timestamp1=pair.second.sensor_ns / 1e9,
            panorama_size=self.panorama_size,
            source="camera",
        )

    @property
    def recording_status(self):
        r = self.engine.recorder
        if r:
            return RecordingStatus(
                self._output or r.path,
                True,
                min(r.counts),
                max((v or 0) for v in r.last_pts) / 1e6,
            )
        m = self._final or {}
        streams = m.get("streams", [])
        return RecordingStatus(
            self._output or Path(),
            False,
            min((s["frames"] for s in streams), default=0),
            max((s.get("last_pts_us") or 0 for s in streams), default=0) / 1e6,
        )

    def start_recording(self, output, overwrite=False):
        self._output = Path(output).resolve()
        self._overwrite = overwrite
        if self._output.exists() and (not overwrite or self._output.suffix != ".mp4"):
            raise FileExistsError(self._output)
        if self.engine.recorder:
            raise RuntimeError("A recording is already active")
        deadline = time.monotonic() + 20
        while not self.engine.pairer.locked:
            if time.monotonic() > deadline:
                raise RuntimeError("Camera synchronization timed out")
            if self.engine.error:
                raise RuntimeError(self.engine.error)
            time.sleep(0.05)
        self.engine.start_recording()
        self._handle = RecordingHandle(
            self._output, self._stop_recording, lambda: self.recording_status
        )
        return self._handle

    def _stop_recording(self):
        manifest = self.engine.stop_recording()
        self._final = manifest
        if not manifest:
            raise RuntimeError("No recording to finalize")
        bundle = self.engine.store.directory(manifest["id"])
        if manifest["state"] != "complete":
            raise RuntimeError(f"Recording needs recovery: {bundle}")
        if self._output.suffix == ".mp4":
            return mux_recording(
                tuple(bundle / s["path"] for s in manifest["streams"]),
                self._output,
                fps=self.fps,
                calibration=self.calibration,
                calibration_result=self.calibration_result,
                overwrite=self._overwrite,
                offsets_us=tuple(
                    s["media_start_offset_us"] for s in manifest["streams"]
                ),
            )
        if self._output.suffix != ".r360":
            raise ValueError(
                f"Use .r360 or .mp4 output; source bundle retained at {bundle}"
            )
        self._output.parent.mkdir(parents=True, exist_ok=True)
        bundle.rename(self._output)
        return self._output

    def stop(self):
        try:
            if self._handle and self._handle.active:
                self._handle.stop()
        finally:
            self.engine.close()
