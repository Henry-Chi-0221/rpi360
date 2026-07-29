"""Headless, step-driven intrinsic calibration session."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional

import cv2
import numpy as np

from ...common.types import (
    CameraCalibration,
    DualCameraIntrinsics,
    InvalidStateError,
    OperationCancelled,
    PathLike,
    PipelineState,
)
from ..camera import CalibrationCamera
from ._internals import (
    _board_geometry,
    _CoverageTracker,
    _draw_intrinsic_preview,
    _find_checkerboard,
    _MotionDetector,
    _solve_guided_intrinsics,
)
from .core import InteractiveIntrinsicConfig, update_calibration_intrinsics


@dataclass(frozen=True)
class CalibrationEvent:
    stage: str
    status: str
    progress: float
    message: str
    preview: Optional[np.ndarray] = None
    diagnostics: Optional[Mapping[str, Any]] = None


class _CalibrationSessionBase:
    def __init__(self, initial_stage: str) -> None:
        self.state = PipelineState.NEW
        self.stage = initial_stage
        self._diagnostics: Dict[str, Any] = {}

    @property
    def diagnostics(self) -> Dict[str, Any]:
        return dict(self._diagnostics)

    def events(self) -> Iterator[CalibrationEvent]:
        while self.state == PipelineState.RUNNING:
            event = self.step()
            if event is not None:
                yield event

    def cancel(self) -> None:
        if self.state == PipelineState.RUNNING:
            self.state = PipelineState.CANCELLED
            self._cleanup()

    def stop(self) -> None:
        self._cleanup()
        if self.state == PipelineState.RUNNING:
            self.state = PipelineState.STOPPED

    def __enter__(self) -> Any:
        return self.start()

    def __exit__(self, *args: Any) -> None:
        self.stop()

    def _cleanup(self) -> None:
        raise NotImplementedError

    def start(self) -> Any:
        raise NotImplementedError

    def step(self) -> Optional[CalibrationEvent]:
        raise NotImplementedError


class IntrinsicCalibrationSession(_CalibrationSessionBase):
    """Calibrate camera 0 and camera 1 intrinsics as an independent stage."""

    def __init__(
        self,
        *,
        camera0: int = 0,
        camera1: int = 1,
        config: Optional[InteractiveIntrinsicConfig] = None,
        camera_factory: Optional[Any] = None,
    ) -> None:
        super().__init__("camera0_intrinsics")
        self.camera_indices = (int(camera0), int(camera1))
        self.config = config or InteractiveIntrinsicConfig()
        self.camera_factory = camera_factory
        self._result: Optional[DualCameraIntrinsics] = None
        self._camera: Optional[CalibrationCamera] = None
        self._motion: Optional[_MotionDetector] = None
        self._coverage: Optional[_CoverageTracker] = None
        self._accepted_corners: List[np.ndarray] = []
        self._area_ratios: List[float] = []
        self._stage_names: List[Optional[str]] = []
        self._latest_intrinsic: Optional[Dict[str, Any]] = None
        self._waiting_for_movement = False
        self._calibrated_cameras: List[CameraCalibration] = []

    @property
    def result(self) -> DualCameraIntrinsics:
        if self._result is None:
            raise InvalidStateError("camera intrinsic calibration has not completed")
        return self._result

    def start(self) -> "IntrinsicCalibrationSession":
        if self.state == PipelineState.RUNNING:
            return self
        self._cleanup()
        self._result = None
        self._diagnostics = {}
        self._calibrated_cameras = []
        self.stage = "camera0_intrinsics"
        try:
            self._start_camera(0)
            self.state = PipelineState.RUNNING
        except Exception:
            self.state = PipelineState.FAILED
            self._cleanup()
            raise
        return self

    def _start_camera(self, logical_index: int) -> None:
        if self._camera is not None:
            self._camera.stop()
        config = self.config
        self._camera = CalibrationCamera(
            self.camera_indices[logical_index],
            config.width,
            config.height,
            config.fps,
            self.camera_factory,
        )
        self._camera.start()
        self._motion = _MotionDetector(config)
        self._coverage = _CoverageTracker(
            config.width, config.height, config.coverage_mask_width
        )
        self._accepted_corners = []
        self._area_ratios = []
        self._stage_names = []
        self._latest_intrinsic = None
        self._waiting_for_movement = False

    def _progress(self, logical_index: int) -> float:
        assert self._coverage is not None
        local = min(
            len(self._accepted_corners) / float(self.config.target_samples),
            self._coverage.ratio() / self.config.coverage_target,
        )
        return (logical_index + max(0.0, min(local, 1.0))) / 2.0

    def _finish_camera(self, logical_index: int) -> None:
        if self._latest_intrinsic is None or self._coverage is None:
            raise RuntimeError(
                "intrinsic calibration completed without a valid solution"
            )
        result = self._latest_intrinsic
        errors = np.asarray(result["per_sample_errors"], dtype=np.float64)
        camera = CameraCalibration(
            self.config.width,
            self.config.height,
            result["K"],
            np.asarray(result["D"]).reshape(4),
            self.config.fisheye_fov_deg,
        )
        self._calibrated_cameras.append(camera)
        self._diagnostics["camera_{}".format(logical_index)] = {
            "camera_index": self.camera_indices[logical_index],
            "accepted_sample_count": len(self._accepted_corners),
            "coverage_ratio": self._coverage.ratio(),
            "opencv_rms_px": float(result["rms"]),
            "mean_reprojection_error_px": float(errors.mean()),
            "max_reprojection_error_px": float(errors.max()),
            "initialization": result["initialization"],
            "board_area_ratios": list(self._area_ratios),
            "guide_stages": [value or "" for value in self._stage_names],
            "K": np.asarray(result["K"]).tolist(),
            "D": np.asarray(result["D"]).reshape(4).tolist(),
            "fisheye_fov_deg": self.config.fisheye_fov_deg,
        }

    def _step_camera(self, logical_index: int) -> CalibrationEvent:
        assert (
            self._camera is not None
            and self._motion is not None
            and self._coverage is not None
        )
        config = self.config
        frame = self._camera.read()
        if frame.shape[:2] != (config.height, config.width):
            frame = cv2.resize(
                frame,
                (config.width, config.height),
                interpolation=cv2.INTER_AREA,
            )
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        motion = self._motion.update(gray)
        if motion["moving"]:
            self._waiting_for_movement = False
        corners: Optional[np.ndarray] = None
        guide = (
            config.guide_stages[len(self._accepted_corners)]
            if len(self._accepted_corners) < len(config.guide_stages)
            else None
        )
        status = "WAITING"
        message = "hold the checkerboard still"

        if motion["static"]:
            corners = _find_checkerboard(gray, config.checkerboard)
            if corners is None:
                status, message = "ALIGN", "checkerboard not detected"
            elif self._waiting_for_movement:
                status, message = "MOVE", "move the checkerboard to a new pose"
            else:
                _, _, center_error, area_ratio = _board_geometry(
                    corners, config.width, config.height
                )
                acceptable = True
                if guide is not None:
                    acceptable = (
                        center_error <= guide.max_center_error_ratio
                        and guide.area_min <= area_ratio <= guide.area_max
                    )
                    if center_error > guide.max_center_error_ratio:
                        message = "move the checkerboard toward the center"
                    elif area_ratio < guide.area_min:
                        message = "move the checkerboard closer"
                    elif area_ratio > guide.area_max:
                        message = "move the checkerboard farther away"
                elif area_ratio < config.minimum_board_area_ratio:
                    acceptable = False
                    message = "checkerboard is too small"

                if acceptable:
                    trial = self._accepted_corners + [corners]
                    trial_result, failure = _solve_guided_intrinsics(
                        trial, config, self._latest_intrinsic
                    )
                    initial_anchor = len(trial) < 2
                    accepted = initial_anchor or (
                        trial_result is not None
                        and float(np.max(trial_result["per_sample_errors"]))
                        < config.maximum_reprojection_error_px
                    )
                    if accepted:
                        self._accepted_corners.append(corners)
                        self._area_ratios.append(area_ratio)
                        self._stage_names.append(
                            guide.name if guide is not None else None
                        )
                        self._coverage.update(corners)
                        if trial_result is not None:
                            self._latest_intrinsic = trial_result
                        status = "ACCEPT"
                        message = "accepted sample {}".format(
                            len(self._accepted_corners)
                        )
                    else:
                        status = "REJECT"
                        message = (
                            failure
                            if trial_result is None
                            else "reprojection error exceeds {:.3f}px".format(
                                config.maximum_reprojection_error_px
                            )
                        )
                    self._waiting_for_movement = True

        preview = _draw_intrinsic_preview(
            frame,
            corners=corners,
            coverage=self._coverage,
            stage=guide,
            status=status,
            reason=message,
            accepted_count=len(self._accepted_corners),
            config=config,
            motion=motion,
            latest_result=self._latest_intrinsic,
        )
        complete = (
            len(self._accepted_corners) >= config.target_samples
            and self._coverage.ratio() >= config.coverage_target
            and self._latest_intrinsic is not None
        )
        if not complete and len(self._accepted_corners) >= config.maximum_samples:
            raise RuntimeError(
                "camera {} reached maximum_samples before completion".format(
                    logical_index
                )
            )

        event = CalibrationEvent(
            stage=self.stage,
            status=status,
            progress=self._progress(logical_index),
            message=message,
            preview=preview,
            diagnostics={
                "accepted": len(self._accepted_corners),
                "target": config.target_samples,
                "coverage": self._coverage.ratio(),
            },
        )
        if complete:
            self._finish_camera(logical_index)
            if logical_index == 0:
                self.stage = "camera1_intrinsics"
                self._start_camera(1)
            else:
                self._result = DualCameraIntrinsics(
                    self._calibrated_cameras[0],
                    self._calibrated_cameras[1],
                )
                self.stage = "complete"
                self.state = PipelineState.COMPLETED
                self._cleanup()
        return event

    def step(self) -> Optional[CalibrationEvent]:
        if self.state == PipelineState.COMPLETED:
            return None
        if self.state == PipelineState.CANCELLED:
            raise OperationCancelled("camera intrinsic calibration was cancelled")
        if self.state != PipelineState.RUNNING:
            raise InvalidStateError(
                "IntrinsicCalibrationSession must be running before step"
            )
        try:
            if self.stage == "camera0_intrinsics":
                return self._step_camera(0)
            if self.stage == "camera1_intrinsics":
                return self._step_camera(1)
            raise InvalidStateError(
                "unknown intrinsic calibration stage {!r}".format(self.stage)
            )
        except Exception:
            self.state = PipelineState.FAILED
            self._cleanup()
            raise

    def run(self) -> DualCameraIntrinsics:
        if self.state != PipelineState.RUNNING:
            self.start()
        for _ in self.events():
            pass
        return self.result

    def save(self, path: PathLike) -> Path:
        return update_calibration_intrinsics(
            path,
            self.result,
            diagnostics=self._diagnostics,
        )

    def _cleanup(self) -> None:
        if self._camera is not None:
            self._camera.stop()
            self._camera = None


__all__ = ["CalibrationEvent", "IntrinsicCalibrationSession"]
