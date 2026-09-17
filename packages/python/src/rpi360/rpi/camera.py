"""Picamera2-only camera adapter for calibration, live preview, and record."""

from __future__ import annotations

import time
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

import numpy as np

from ..common.types import CaptureError, InvalidStateError


class CameraDevice:
    """One Picamera2 camera with BGR preview and optional H.264 recording."""

    def __init__(
        self,
        index: int,
        *,
        preview_size: Tuple[int, int] = (1640, 1232),
        record_size: Optional[Tuple[int, int]] = None,
        fps: float = 21.0,
        recording_capable: bool = True,
        camera_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.index = int(index)
        self.preview_size = tuple(map(int, preview_size))
        self.requested_record_size = (
            None if record_size is None else tuple(map(int, record_size))
        )
        self.fps = float(fps)
        self.recording_capable = bool(recording_capable)
        self.camera_factory = camera_factory
        if min(self.preview_size) <= 0 or self.fps <= 0.0:
            raise ValueError("preview size and fps must be positive")
        if self.requested_record_size is not None:
            if min(self.requested_record_size) <= 0:
                raise ValueError("record size must be positive")
            if any(value % 2 for value in self.requested_record_size):
                raise ValueError("H.264 record width and height must be even")
        self.record_size: Optional[Tuple[int, int]] = None
        self._camera: Optional[Any] = None
        self._encoder: Optional[Any] = None
        self._preview_stream = "main"

    @property
    def running(self) -> bool:
        return self._camera is not None

    @property
    def encoder_name(self) -> Optional[str]:
        return None if self._encoder is None else type(self._encoder).__name__

    def _create_camera(self) -> Any:
        if self.camera_factory is not None:
            try:
                return self.camera_factory(camera_num=self.index)
            except TypeError:
                return self.camera_factory(self.index)
        try:
            from picamera2 import Picamera2
        except (ImportError, ModuleNotFoundError) as exc:
            raise CaptureError(
                "Picamera2 is required for RPi capture; install the Raspberry "
                "Pi OS package python3-picamera2"
            ) from exc
        return Picamera2(camera_num=self.index)

    def start(self) -> "CameraDevice":
        if self.running:
            return self
        camera = self._create_camera()
        try:
            if not self.recording_capable:
                configuration = camera.create_preview_configuration(
                    main={"size": self.preview_size, "format": "RGB888"},
                    controls={"FrameRate": self.fps},
                    buffer_count=4,
                )
                self.record_size = self.preview_size
                self._preview_stream = "main"
            else:
                record_size = self.requested_record_size
                if record_size is None:
                    modes = [
                        tuple(map(int, mode["size"]))
                        for mode in camera.sensor_modes
                        if "size" in mode
                        and all(int(value) % 2 == 0 for value in mode["size"])
                    ]
                    if not modes:
                        raise CaptureError("camera exposes no even-sized video mode")
                    record_size = max(modes, key=lambda item: item[0] * item[1])
                configuration = camera.create_video_configuration(
                    main={"size": record_size, "format": "YUV420"},
                    lores={"size": self.preview_size, "format": "RGB888"},
                    controls={"FrameRate": self.fps},
                    buffer_count=6,
                )
                self.record_size = record_size
                self._preview_stream = "lores"
            camera.configure(configuration)
            camera.start()
        except BaseException:
            camera.close()
            raise
        self._camera = camera
        return self

    def read(self) -> Tuple[np.ndarray, float]:
        if self._camera is None:
            raise InvalidStateError("camera is not started")
        frame = self._camera.capture_array(self._preview_stream)
        timestamp = time.monotonic()
        if frame is None:
            raise CaptureError(
                "Picamera2 camera {} returned no preview frame".format(self.index)
            )
        array = np.asarray(frame)
        expected_shape = (self.preview_size[1], self.preview_size[0])
        if array.ndim != 3 or array.shape[:2] != expected_shape:
            raise CaptureError(
                "Picamera2 camera {} returned shape {}; expected {}x{} "
                "RGB888/BGR bytes".format(
                    self.index,
                    array.shape,
                    self.preview_size[0],
                    self.preview_size[1],
                )
            )
        if array.shape[2] < 3 or array.dtype != np.uint8:
            raise CaptureError(
                "Picamera2 camera {} must return uint8 RGB888/BGR bytes, "
                "got shape {} dtype {}".format(
                    self.index,
                    array.shape,
                    array.dtype,
                )
            )
        # Picamera2's RGB888 capture_array byte ordering was verified against
        # the original RPi implementation and is OpenCV BGR. Do not swap it.
        return np.ascontiguousarray(array[:, :, :3]), timestamp

    def start_recording(self, output: Path) -> Path:
        if self._camera is None or self.record_size is None:
            raise InvalidStateError("camera must be started before recording")
        if not self.recording_capable:
            raise InvalidStateError("this camera was opened for calibration only")
        if self._encoder is not None:
            raise InvalidStateError("camera is already recording")
        try:
            from picamera2.encoders import H264Encoder
            from picamera2.outputs import FileOutput
        except (ImportError, ModuleNotFoundError) as exc:
            raise CaptureError(
                "the installed Picamera2 package has no H.264 encoder support"
            ) from exc

        try:
            encoder = H264Encoder(
                repeat=True,
                iperiod=max(1, int(round(self.fps * 2.0))),
                # Picamera2's Pi 5 LibavH264Encoder forwards this value to
                # PyAV, whose rate API requires a rational, not a float.
                framerate=Fraction(str(self.fps)).limit_denominator(1000),
            )
        except (ImportError, ModuleNotFoundError) as exc:
            raise CaptureError(
                "Picamera2 H.264 encoding requires its Raspberry Pi OS "
                "libav/PyAV dependencies"
            ) from exc
        # On Pi 5 H264Encoder aliases to the multi-threaded libx264 encoder.
        # Picamera2 already defaults to ultrafast + zerolatency; make the
        # speed-oriented choice explicit when that implementation is active.
        if hasattr(encoder, "preset"):
            encoder.preset = "ultrafast"
        if hasattr(encoder, "threads"):
            pixels = self.record_size[0] * self.record_size[1]
            encoder.threads = 1 if pixels <= 1920 * 1080 else 2
        try:
            self._camera.start_encoder(encoder, FileOutput(str(output)), name="main")
        except TypeError:
            self._camera.start_encoder(
                encoder, FileOutput(str(output)), stream_name="main"
            )
        self._encoder = encoder
        return output

    def stop_recording(self) -> None:
        if self._encoder is None:
            return
        encoder = self._encoder
        self._encoder = None
        try:
            self._camera.stop_encoder(encoder)
        except TypeError:
            self._camera.stop_encoder()

    def stop(self) -> None:
        self.stop_recording()
        camera = self._camera
        self._camera = None
        if camera is not None:
            camera.stop()
            camera.close()

    def __enter__(self) -> "CameraDevice":
        return self.start()

    def __exit__(self, *args: Any) -> None:
        self.stop()


class CalibrationCamera:
    """Calibration-facing wrapper over the shared CameraDevice."""

    def __init__(
        self,
        camera_index: int,
        width: int,
        height: int,
        fps: float,
        camera_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.device = CameraDevice(
            camera_index,
            preview_size=(width, height),
            fps=fps,
            recording_capable=False,
            camera_factory=camera_factory,
        )

    def start(self) -> None:
        self.device.start()

    def read(self) -> np.ndarray:
        return self.device.read()[0]

    def stop(self) -> None:
        self.device.stop()

    def __enter__(self) -> "CalibrationCamera":
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()


__all__ = ["CalibrationCamera", "CameraDevice"]
