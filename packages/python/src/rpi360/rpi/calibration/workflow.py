"""The production two-stage rig calibration workflow for Raspberry Pi."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional, Tuple

import cv2

from ...common.types import PathLike
from .core import InteractiveRigConfig
from .recording import RigVideoRecorder
from .session import CalibrationEvent
from .video import VideoRigCalibrationSession


class RigCalibrationWorkflow:
    """Record first, close both cameras, then solve the rig rotation.

    The work directory is intentionally persistent. If a solve is interrupted,
    rerun with ``resume=True`` to reuse the captured camera tracks.
    """

    def __init__(
        self,
        calibration_result: PathLike,
        *,
        work_directory: PathLike = "rig-calibration-work",
        camera_indices: Tuple[int, int] = (0, 1),
        config: Optional[InteractiveRigConfig] = None,
        record_size: Optional[Tuple[int, int]] = None,
        opencv_threads: int = 2,
    ) -> None:
        self.calibration_path = Path(calibration_result)
        self.work_directory = Path(work_directory)
        self.camera_indices = tuple(map(int, camera_indices))
        self.config = config or InteractiveRigConfig(
            sample_count=20,
            capture_seconds=30.0,
            feature_scale=1.0,
        )
        self.record_size = (
            None if record_size is None else tuple(map(int, record_size))
        )
        self.opencv_threads = int(opencv_threads)
        if self.opencv_threads < 1:
            raise ValueError("opencv_threads must be positive")

    @property
    def camera_videos(self) -> Tuple[Path, Path]:
        return (
            self.work_directory / "cam0.mp4",
            self.work_directory / "cam1.mp4",
        )

    def _validate_resume(self) -> None:
        missing = [str(path) for path in self.camera_videos if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                "cannot resume; missing recorded input: {}".format(
                    ", ".join(missing)
                )
            )

    def record(self, *, duration: Optional[float] = None) -> Path:
        seconds = self.config.capture_seconds if duration is None else float(duration)
        if seconds <= 0.0:
            raise ValueError("recording duration must be positive")
        recorder = RigVideoRecorder(
            self.calibration_path,
            self.work_directory,
            camera_indices=self.camera_indices,
            record_size=self.record_size,
            fps=self.config.fps,
        ).start()
        try:
            time.sleep(seconds)
        except KeyboardInterrupt:
            pass
        return recorder.stop().directory

    def solve(
        self,
        *,
        on_event: Optional[Callable[[CalibrationEvent], None]] = None,
    ) -> Path:
        self._validate_resume()
        previous_threads = cv2.getNumThreads()
        cv2.setNumThreads(self.opencv_threads)
        try:
            session = VideoRigCalibrationSession(
                self.camera_videos[0],
                self.camera_videos[1],
                self.calibration_path,
                config=self.config,
                check_stability=True,
            )
            with session:
                for event in session.events():
                    if on_event is not None:
                        on_event(event)
            return session.save(self.calibration_path)
        finally:
            cv2.setNumThreads(previous_threads)

    def run(
        self,
        *,
        resume: bool = False,
        on_event: Optional[Callable[[CalibrationEvent], None]] = None,
    ) -> Path:
        if resume:
            self._validate_resume()
        else:
            self.record()
        return self.solve(on_event=on_event)


__all__ = ["RigCalibrationWorkflow"]
