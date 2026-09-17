"""Latest-frame dual-camera source for Player.live."""

from __future__ import annotations

import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional, Tuple

from ..common.frames import FrameBundle
from ..common.metadata import (
    calibration_profile_from_result,
    load_calibration_result,
)
from ..common.types import CaptureError, InvalidStateError, PathLike
from .camera import CameraDevice
from .encoding import DualEncoderSession
from .recording import (
    RecordingHandle,
    RecordingStatus,
    discard_recording_directory,
    mux_recording,
    recording_directory,
)


class LiveSource:
    """Capture continuously and expose only the most recent complete pair."""

    def __new__(cls, *args, **kwargs):
        # The injectable v1 diagnostic adapter remains for downstream test rigs.
        # Real hardware always uses the v2 sensor-clock capture engine.
        if kwargs.get("camera_factory") is None:
            from ..compat.capture import ServiceLiveSource

            return ServiceLiveSource(*args, **kwargs)
        return super().__new__(cls)

    kind = "live"
    supports_timeline = False

    def __init__(
        self,
        calibration_json: PathLike,
        *,
        camera_indices: Tuple[int, int] = (0, 1),
        panorama_size: Tuple[int, int] = (2048, 1024),
        preview_size: Optional[Tuple[int, int]] = None,
        record_size: Optional[Tuple[int, int]] = None,
        fps: Optional[float] = None,
        camera_factory: Optional[Any] = None,
    ) -> None:
        self.calibration_path = Path(calibration_json)
        self._calibration_result = load_calibration_result(calibration_json)
        self._calibration = calibration_profile_from_result(self._calibration_result)
        self.panorama_size = tuple(map(int, panorama_size))
        self._fps = float(fps or 21.0)
        size0 = preview_size or (
            self._calibration.camera0.width,
            self._calibration.camera0.height,
        )
        size1 = preview_size or (
            self._calibration.camera1.width,
            self._calibration.camera1.height,
        )
        self.devices = (
            CameraDevice(
                camera_indices[0],
                preview_size=size0,
                record_size=record_size or size0,
                fps=self._fps,
                camera_factory=camera_factory,
            ),
            CameraDevice(
                camera_indices[1],
                preview_size=size1,
                record_size=record_size or size1,
                fps=self._fps,
                camera_factory=camera_factory,
            ),
        )
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._latest: Optional[FrameBundle] = None
        self._sequence = 0
        self._delivered_sequence = 0
        self._failure: Optional[BaseException] = None
        self._recording_lock = threading.RLock()
        self._recording_handle: Optional[RecordingHandle] = None
        self._recording_dir: Optional[Path] = None
        self._recording_tracks: Optional[Tuple[Path, Path]] = None
        self._recording_encoder: Optional[DualEncoderSession] = None
        self._recording_output: Optional[Path] = None
        self._recording_started: Optional[float] = None
        self._recording_start_sequence = 0
        self._recording_overwrite = False
        self._last_recording_count = 0
        self._last_recording_duration = 0.0

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def calibration(self) -> Any:
        return self._calibration

    @property
    def calibration_result(self) -> dict:
        return copy.deepcopy(self._calibration_result)

    @property
    def processing_sizes(self) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """BGR sizes passed to the source-neutral FrameBundle renderer."""
        return self.devices[0].preview_size, self.devices[1].preview_size

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def inspect(self) -> dict:
        """Describe the live source using the same frame contract as MP4."""
        return {
            "source": "live",
            "fps": self.fps,
            "camera_indices": [device.index for device in self.devices],
            "processing_sizes": [list(size) for size in self.processing_sizes],
            "record_sizes": [
                None if device.record_size is None else list(device.record_size)
                for device in self.devices
            ],
            "pixel_format": "bgr24",
            "panorama_size": list(self.panorama_size),
            "calibration_result": self.calibration_result,
        }

    def start(self) -> "LiveSource":
        if self.running:
            return self
        started = []
        try:
            for device in self.devices:
                device.start()
                started.append(device)
        except BaseException:
            for device in reversed(started):
                device.stop()
            raise
        self._failure = None
        self._latest = None
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="rpi360-live-capture",
            daemon=True,
        )
        self._thread.start()
        return self

    def _capture_loop(self) -> None:
        try:
            with ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="rpi360-camera"
            ) as executor:
                while not self._stop_event.is_set():
                    future0 = executor.submit(self.devices[0].read)
                    future1 = executor.submit(self.devices[1].read)
                    frame0, timestamp0 = future0.result()
                    frame1, timestamp1 = future1.result()
                    self._sequence += 1
                    bundle = FrameBundle(
                        frame0,
                        frame1,
                        self._calibration,
                        index=self._sequence,
                        timestamp0=timestamp0,
                        timestamp1=timestamp1,
                        panorama_size=self.panorama_size,
                        source="camera",
                    )
                    with self._condition:
                        self._latest = bundle
                        self._condition.notify_all()
        except BaseException as exc:
            if not self._stop_event.is_set():
                with self._condition:
                    self._failure = exc
                    self._condition.notify_all()

    def read(self, timeout: Optional[float] = 0.03) -> Optional[FrameBundle]:
        if not self.running and self._failure is None:
            raise InvalidStateError("live source is not started")
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        with self._condition:
            while True:
                if (
                    self._latest is not None
                    and self._latest.index > self._delivered_sequence
                ):
                    self._delivered_sequence = self._latest.index
                    return self._latest
                if self._failure is not None:
                    if isinstance(self._failure, CaptureError):
                        raise self._failure
                    raise CaptureError(str(self._failure)) from self._failure
                if not self.running:
                    raise CaptureError("live capture stopped")
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0.0:
                    return None
                self._condition.wait(remaining)

    @property
    def recording_status(self) -> RecordingStatus:
        with self._recording_lock:
            started = self._recording_started
            active = self._recording_tracks is not None
            count = (
                max(0, self._sequence - self._recording_start_sequence)
                if active
                else self._last_recording_count
            )
            duration = (
                max(0.0, time.monotonic() - started)
                if active and started is not None
                else self._last_recording_duration
            )
            return RecordingStatus(
                output=self._recording_output or Path(),
                active=active,
                frame_count=count,
                duration=duration,
            )

    def start_recording(
        self, output: PathLike, *, overwrite: bool = False
    ) -> RecordingHandle:
        if not self.running:
            raise InvalidStateError("live source must be started before recording")
        output_path = Path(output)
        if output_path.suffix.lower() != ".mp4":
            raise ValueError("recording output must use an .mp4 suffix")
        if output_path.exists() and not overwrite:
            raise FileExistsError(str(output_path))
        with self._recording_lock:
            if self._recording_tracks is not None:
                raise InvalidStateError("a recording is already active")
            directory = recording_directory()
            tracks = (
                directory / "camera0.h264",
                directory / "camera1.h264",
            )
            try:
                encoder = DualEncoderSession(self.devices, tracks).start()
            except BaseException:
                discard_recording_directory(directory)
                raise
            self._recording_dir = directory
            self._recording_tracks = tracks
            self._recording_encoder = encoder
            self._recording_output = output_path
            self._recording_started = time.monotonic()
            self._recording_start_sequence = self._sequence
            self._recording_overwrite = overwrite
            handle = RecordingHandle(
                output_path, self._stop_recording, lambda: self.recording_status
            )
            self._recording_handle = handle
            return handle

    def _stop_recording(self) -> Path:
        with self._recording_lock:
            if self._recording_tracks is None:
                if self._recording_output is not None:
                    return self._recording_output
                raise InvalidStateError("no recording is active")
            assert self._recording_encoder is not None
            self._recording_encoder.stop()
            tracks = self._recording_tracks
            directory = self._recording_dir
            output = self._recording_output
            overwrite = self._recording_overwrite
            started = self._recording_started
            count = max(0, self._sequence - self._recording_start_sequence)
            self._recording_tracks = None
            self._recording_encoder = None
            self._recording_dir = None
            self._recording_started = None
        assert output is not None
        self._last_recording_count = count
        self._last_recording_duration = (
            max(0.0, time.monotonic() - started) if started is not None else 0.0
        )
        if count <= 0:
            raise RuntimeError(
                "recording ended before a complete frame pair; "
                f"sources retained at {directory}"
            )
        result = mux_recording(
            tracks,
            output,
            fps=self._fps,
            calibration=self._calibration,
            calibration_result=self._calibration_result,
            overwrite=overwrite,
        )
        discard_recording_directory(directory)
        return result

    def stop(self) -> None:
        handle = self._recording_handle
        recording_error: Optional[BaseException] = None
        try:
            if handle is not None and handle.active:
                handle.stop()
        except BaseException as exc:
            recording_error = exc
        finally:
            self._recording_handle = None
            self._stop_event.set()
            thread = self._thread
            if (
                thread is not None
                and thread.is_alive()
                and threading.current_thread() is not thread
            ):
                thread.join(timeout=3.0)
            for device in self.devices:
                device.stop()
            self._thread = None
            with self._condition:
                self._condition.notify_all()
        if recording_error is not None:
            raise recording_error


__all__ = ["LiveSource"]
