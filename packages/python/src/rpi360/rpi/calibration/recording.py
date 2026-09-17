"""Picamera2-only recording of inputs for offline rig calibration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

from ...common.metadata import load_calibration_document, require_executable
from ...common.types import DualCameraIntrinsics, InvalidStateError, PathLike
from ..camera import CameraDevice
from ..encoding import DualEncoderSession


@dataclass(frozen=True)
class RigVideoCaptureResult:
    """Paths published by :class:`RigVideoRecorder`."""

    directory: Path
    camera0_video: Path
    camera1_video: Path
    calibration_result: Path
    manifest: Path


class RigVideoRecorder:
    """Record two raw fisheye streams for later SIFT rig calibration.

    This is deliberately not an RPI360 playback MP4: rig rotation does not
    exist yet.  The output directory contains ``cam0.mp4``, ``cam1.mp4``, and
    the intrinsics-stage ``calibration-result.json`` needed by the offline
    calibration session.
    """

    def __init__(
        self,
        calibration_result: PathLike,
        output_directory: PathLike,
        *,
        camera_indices: Tuple[int, int] = (0, 1),
        record_size: Optional[Tuple[int, int]] = None,
        preview_size: Tuple[int, int] = (640, 480),
        fps: float = 21.0,
        camera_factory: Optional[Any] = None,
    ) -> None:
        self.calibration_path = Path(calibration_result)
        document = load_calibration_document(self.calibration_path)
        self.intrinsics = DualCameraIntrinsics.from_dict(document["calibration"])
        self.output_directory = Path(output_directory)
        self.camera_indices = tuple(map(int, camera_indices))
        self.record_size = (
            tuple(map(int, record_size)) if record_size is not None else None
        )
        self.preview_size = tuple(map(int, preview_size))
        self.fps = float(fps)
        self.camera_factory = camera_factory
        if self.output_directory.exists():
            raise FileExistsError(str(self.output_directory))
        if self.fps <= 0.0:
            raise ValueError("fps must be positive")

        self._devices: Optional[Tuple[CameraDevice, CameraDevice]] = None
        self._temporary_directory: Optional[Path] = None
        self._tracks: Optional[Tuple[Path, Path]] = None
        self._started_at: Optional[float] = None
        self._encoder_started_at: Optional[Tuple[float, float]] = None
        self._encoder: Optional[DualEncoderSession] = None
        self._result: Optional[RigVideoCaptureResult] = None

    @property
    def active(self) -> bool:
        return self._tracks is not None

    @property
    def result(self) -> Optional[RigVideoCaptureResult]:
        return self._result

    def _camera_size(self, logical_index: int) -> Tuple[int, int]:
        if self.record_size is not None:
            return self.record_size
        calibration = (
            self.intrinsics.camera0
            if logical_index == 0
            else self.intrinsics.camera1
        )
        return calibration.width, calibration.height

    def start(self) -> "RigVideoRecorder":
        if self.active:
            return self
        if self._result is not None:
            raise InvalidStateError("rig video recorder has already completed")
        self.output_directory.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(
                prefix=".{}-".format(self.output_directory.name),
                dir=str(self.output_directory.parent),
            )
        )
        devices = (
            CameraDevice(
                self.camera_indices[0],
                preview_size=self.preview_size,
                record_size=self._camera_size(0),
                fps=self.fps,
                camera_factory=self.camera_factory,
            ),
            CameraDevice(
                self.camera_indices[1],
                preview_size=self.preview_size,
                record_size=self._camera_size(1),
                fps=self.fps,
                camera_factory=self.camera_factory,
            ),
        )
        tracks = (temporary / "cam0.h264", temporary / "cam1.h264")
        try:
            devices[0].start()
            devices[1].start()
            encoder = DualEncoderSession(devices, tracks).start()
            encoder0_started, encoder1_started = encoder.require_started_at()
        except BaseException:
            for device in devices:
                device.stop()
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        self._devices = devices
        self._temporary_directory = temporary
        self._tracks = tracks
        self._started_at = encoder0_started
        self._encoder_started_at = (encoder0_started, encoder1_started)
        self._encoder = encoder
        return self

    def _remux_track(self, source: Path, output: Path) -> None:
        completed = subprocess.run(
            [
                require_executable("ffmpeg"),
                "-v",
                "error",
                "-y",
                "-r",
                "{:.9g}".format(self.fps),
                "-i",
                str(source),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "could not remux calibration track: {}".format(
                    completed.stderr.decode("utf-8", errors="replace").strip()
                )
            )

    def stop(self) -> RigVideoCaptureResult:
        if self._result is not None:
            return self._result
        if (
            self._devices is None
            or self._tracks is None
            or self._temporary_directory is None
            or self._started_at is None
            or self._encoder_started_at is None
            or self._encoder is None
        ):
            raise InvalidStateError("rig video recorder is not running")
        devices = self._devices
        tracks = self._tracks
        temporary = self._temporary_directory
        duration = max(0.0, time.monotonic() - self._started_at)
        encoder = self._encoder
        self._tracks = None
        self._devices = None
        self._temporary_directory = None
        self._encoder = None
        try:
            encoder.stop()
            for device in devices:
                device.stop()
            if duration <= 0.0 or any(
                not track.is_file() or track.stat().st_size == 0 for track in tracks
            ):
                raise RuntimeError("rig calibration recording contains no video")
            camera0_video = temporary / "cam0.mp4"
            camera1_video = temporary / "cam1.mp4"
            self._remux_track(tracks[0], camera0_video)
            self._remux_track(tracks[1], camera1_video)
            for track in tracks:
                track.unlink()
            calibration_copy = temporary / "calibration-result.json"
            shutil.copy2(self.calibration_path, calibration_copy)
            manifest = temporary / "capture.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "pairing": "same frame index",
                        "camera_indices": list(self.camera_indices),
                        "record_sizes": [
                            list(devices[0].record_size or self._camera_size(0)),
                            list(devices[1].record_size or self._camera_size(1)),
                        ],
                        "fps": self.fps,
                        "duration_seconds": duration,
                        "encoder_start_difference_seconds": abs(
                            self._encoder_started_at[1]
                            - self._encoder_started_at[0]
                        ),
                        "files": {
                            "camera_0": "cam0.mp4",
                            "camera_1": "cam1.mp4",
                            "calibration_result": "calibration-result.json",
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(str(temporary), str(self.output_directory))
        except BaseException:
            for device in devices:
                device.stop()
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        self._result = RigVideoCaptureResult(
            directory=self.output_directory,
            camera0_video=self.output_directory / "cam0.mp4",
            camera1_video=self.output_directory / "cam1.mp4",
            calibration_result=self.output_directory / "calibration-result.json",
            manifest=self.output_directory / "capture.json",
        )
        return self._result

    def cancel(self) -> None:
        devices = self._devices
        temporary = self._temporary_directory
        self._tracks = None
        self._devices = None
        self._temporary_directory = None
        if devices is not None:
            for device in devices:
                device.stop()
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)

    def __enter__(self) -> "RigVideoRecorder":
        return self.start()

    def __exit__(self, exc_type: Any, *_args: Any) -> None:
        if exc_type is None:
            self.stop()
        else:
            self.cancel()


__all__ = ["RigVideoCaptureResult", "RigVideoRecorder"]
