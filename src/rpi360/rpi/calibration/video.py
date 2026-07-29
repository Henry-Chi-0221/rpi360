"""Offline rig calibration from two recorded fisheye MP4 streams.

This module only owns video sampling and session lifecycle.  Fisheye remapping,
SIFT matching, spherical RANSAC, and Kabsch/SVD refinement are shared with the
interactive sample-quality implementation.
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple, Union

import cv2
import numpy as np

from ...common.metadata import load_calibration_document
from ...common.types import (
    CalibrationProfile,
    DualCameraIntrinsics,
    InvalidStateError,
    OperationCancelled,
    PathLike,
    PipelineState,
)
from .core import (
    InteractiveRigConfig,
    RigSampleReview,
    RigSampleReviewer,
    solve_rig_samples,
    update_calibration_profile,
)
from .session import CalibrationEvent


class VideoRigCalibrationSession:
    """Step-driven rig calibration using two frame-index-paired MP4 files.

    The two input files are expected to start from the same capture instant and
    contain camera 0 and camera 1 respectively.  Frame index pairing matches the
    proven reference data and the RPi calibration recorder provided by this
    package.
    """

    def __init__(
        self,
        camera0_video: PathLike,
        camera1_video: PathLike,
        calibration_result: Union[PathLike, DualCameraIntrinsics],
        *,
        config: Optional[InteractiveRigConfig] = None,
        sample_indices: Optional[Sequence[int]] = None,
        check_stability: bool = True,
        stability_search_frames: int = 30,
        capture_factory: Optional[Any] = None,
    ) -> None:
        self.video_paths = (Path(camera0_video), Path(camera1_video))
        for path in self.video_paths:
            if path.suffix.lower() != ".mp4":
                raise ValueError("rig calibration video inputs must use .mp4")
            if not path.is_file():
                raise FileNotFoundError(str(path))

        if isinstance(calibration_result, DualCameraIntrinsics):
            self.intrinsics = calibration_result
            self.calibration_path: Optional[Path] = None
            self._intrinsic_diagnostics: Dict[str, Any] = {}
        else:
            self.calibration_path = Path(calibration_result)
            document = load_calibration_document(self.calibration_path)
            self.intrinsics = DualCameraIntrinsics.from_dict(document["calibration"])
            self._intrinsic_diagnostics = dict(
                document["diagnostics"].get("intrinsics", {})
            )

        self.config = config or InteractiveRigConfig(
            width=self.intrinsics.camera0.width,
            height=self.intrinsics.camera0.height,
        )
        self.requested_sample_indices = (
            None
            if sample_indices is None
            else tuple(int(value) for value in sample_indices)
        )
        if self.requested_sample_indices is not None:
            if len(self.requested_sample_indices) < 2:
                raise ValueError("sample_indices must contain at least two frames")
            if (
                tuple(sorted(set(self.requested_sample_indices)))
                != self.requested_sample_indices
            ):
                raise ValueError("sample_indices must be unique and increasing")
            if self.requested_sample_indices[0] < 0:
                raise ValueError("sample_indices must be non-negative")
        self.check_stability = bool(check_stability)
        self.stability_search_frames = int(stability_search_frames)
        if self.stability_search_frames < 0:
            raise ValueError("stability_search_frames must be non-negative")
        self.capture_factory = capture_factory or cv2.VideoCapture

        self.state = PipelineState.NEW
        self.stage = "video_samples"
        self._captures: Optional[Tuple[Any, Any]] = None
        self._video_info: List[Dict[str, Any]] = []
        self._sample_targets: Tuple[int, ...] = ()
        self._sample_cursor = 0
        self._samples: List[Tuple[np.ndarray, np.ndarray]] = []
        self._accepted_matches: List[
            Tuple[np.ndarray, np.ndarray, Mapping[str, Any]]
        ] = []
        self._timing: List[Dict[str, float]] = []
        self._review_history: List[Dict[str, Any]] = []
        self._reviewer: Optional[RigSampleReviewer] = None
        self._last_review: Optional[RigSampleReview] = None
        self._result: Optional[CalibrationProfile] = None
        self._diagnostics: Dict[str, Any] = {
            "intrinsics": self._intrinsic_diagnostics
        }
        self._review_seconds = 0.0

    @property
    def result(self) -> CalibrationProfile:
        if self._result is None:
            raise InvalidStateError("video rig calibration has not completed")
        return self._result

    @property
    def diagnostics(self) -> Dict[str, Any]:
        return dict(self._diagnostics)

    @property
    def last_review(self) -> Optional[RigSampleReview]:
        """Latest inspectable equirectangular images and feature matches."""
        return self._last_review

    @property
    def sample_indices(self) -> Tuple[int, ...]:
        """Actual accepted frame indices, after optional stability search."""
        return tuple(int(item["frame_index"]) for item in self._timing)

    @staticmethod
    def _capture_info(capture: Any, path: Path) -> Dict[str, Any]:
        frame_count = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if frame_count <= 0 or width <= 0 or height <= 0:
            raise RuntimeError("could not read video dimensions from {}".format(path))
        if not math.isfinite(fps) or fps <= 0.0:
            raise RuntimeError("could not read video FPS from {}".format(path))
        return {
            "path": str(path),
            "frame_count": frame_count,
            "width": width,
            "height": height,
            "fps": fps,
            "duration": frame_count / fps,
        }

    def _open_videos(self) -> None:
        captures = tuple(self.capture_factory(str(path)) for path in self.video_paths)
        try:
            for capture, path in zip(captures, self.video_paths):
                if not capture.isOpened():
                    raise RuntimeError(
                        "could not open rig calibration video {}".format(path)
                    )
            info = [
                self._capture_info(capture, path)
                for capture, path in zip(captures, self.video_paths)
            ]
        except BaseException:
            for capture in captures:
                capture.release()
            raise
        self._captures = captures
        self._video_info = info

    def _make_sample_targets(self) -> Tuple[int, ...]:
        common_frames = min(item["frame_count"] for item in self._video_info)
        if self.requested_sample_indices is not None:
            if self.requested_sample_indices[-1] >= common_frames:
                raise ValueError(
                    "sample frame {} exceeds common frame count {}".format(
                        self.requested_sample_indices[-1],
                        common_frames,
                    )
                )
            return self.requested_sample_indices
        first = self.config.stable_frames if self.check_stability else 0
        last = common_frames - 1
        if last <= first:
            raise RuntimeError("videos are too short for stability-reviewed sampling")
        indices = np.rint(
            np.linspace(first, last, self.config.sample_count)
        ).astype(np.int64)
        targets = tuple(int(value) for value in indices)
        if len(set(targets)) != len(targets):
            raise RuntimeError("videos do not contain enough frames for sample_count")
        return targets

    def start(self) -> "VideoRigCalibrationSession":
        if self.state == PipelineState.RUNNING:
            return self
        self._cleanup()
        self._result = None
        self._diagnostics = {"intrinsics": self._intrinsic_diagnostics}
        self._sample_cursor = 0
        self._samples = []
        self._accepted_matches = []
        self._timing = []
        self._review_history = []
        self._last_review = None
        self._review_seconds = 0.0
        self.stage = "video_samples"
        try:
            self._open_videos()
            self._sample_targets = self._make_sample_targets()
            self._reviewer = RigSampleReviewer(
                self.intrinsics.camera0,
                self.intrinsics.camera1,
                self.config,
            )
            self.state = PipelineState.RUNNING
        except Exception:
            self.state = PipelineState.FAILED
            self._cleanup()
            raise
        return self

    @staticmethod
    def _motion_image(frame: np.ndarray, resize_width: int) -> np.ndarray:
        height, width = frame.shape[:2]
        if width > resize_width:
            scale = resize_width / float(width)
            frame = cv2.resize(
                frame,
                (resize_width, max(1, int(round(height * scale)))),
                interpolation=cv2.INTER_AREA,
            )
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(gray, (5, 5), 0)

    def _read_stable_pair(
        self,
        target: int,
    ) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
        assert self._captures is not None
        config = self.config
        required = config.stable_frames if self.check_stability else 0
        start = max(0, target - required)
        common_frames = min(item["frame_count"] for item in self._video_info)
        stop = min(common_frames - 1, target + self.stability_search_frames)
        for capture in self._captures:
            capture.set(cv2.CAP_PROP_POS_FRAMES, start)

        previous: List[Optional[np.ndarray]] = [None, None]
        still_counts = [0, 0]
        motion_scores = [float("inf"), float("inf")]
        for frame_index in range(start, stop + 1):
            frames: List[np.ndarray] = []
            for camera_index, capture in enumerate(self._captures):
                success, frame = capture.read()
                if not success or frame is None:
                    raise RuntimeError(
                        "could not decode camera {} frame {}".format(
                            camera_index,
                            frame_index,
                        )
                    )
                frames.append(frame)
                motion_image = self._motion_image(
                    frame,
                    config.motion_resize_width,
                )
                if previous[camera_index] is None:
                    moving = True
                else:
                    motion_scores[camera_index] = float(
                        np.mean(
                            cv2.absdiff(
                                motion_image,
                                previous[camera_index],
                            )
                        )
                    )
                    moving = (
                        motion_scores[camera_index] > config.motion_threshold
                    )
                still_counts[camera_index] = (
                    0 if moving else still_counts[camera_index] + 1
                )
                previous[camera_index] = motion_image

            stable = not self.check_stability or min(still_counts) >= required
            if frame_index >= target and stable:
                resized = []
                for frame in frames:
                    if frame.shape[:2] != (config.height, config.width):
                        frame = cv2.resize(
                            frame,
                            (config.width, config.height),
                            interpolation=cv2.INTER_AREA,
                        )
                    resized.append(np.ascontiguousarray(frame))
                return (
                    resized[0],
                    resized[1],
                    {
                        "target_frame_index": target,
                        "frame_index": frame_index,
                        "stable": stable,
                        "stable_frames_camera0": still_counts[0],
                        "stable_frames_camera1": still_counts[1],
                        "motion_score_camera0": motion_scores[0],
                        "motion_score_camera1": motion_scores[1],
                    },
                )
        raise RuntimeError(
            "no stable frame pair found from frame {} through {}".format(
                target,
                stop,
            )
        )

    def _step_sample(self) -> CalibrationEvent:
        assert self._reviewer is not None
        target = self._sample_targets[self._sample_cursor]
        frame0, frame1, selection = self._read_stable_pair(target)
        started = time.perf_counter()
        review = self._reviewer.review(frame0, frame1)
        review_seconds = time.perf_counter() - started
        self._review_seconds += review_seconds
        self._last_review = review
        history = {
            "sample": self._sample_cursor,
            **selection,
            "accepted": review.accepted,
            "reason": review.reason,
            "review_seconds": review_seconds,
            **dict(review.diagnostics),
        }
        self._review_history.append(history)
        if review.accepted:
            self._samples.append((frame0.copy(), frame1.copy()))
            self._accepted_matches.append(
                (
                    review.points0.copy(),
                    review.points1.copy(),
                    {
                        "keypoints0": review.diagnostics.get("keypoints0", 0),
                        "keypoints1": review.diagnostics.get("keypoints1", 0),
                        "matches": review.diagnostics.get("matches", 0),
                    },
                )
            )
            frame_index = int(selection["frame_index"])
            timestamp0 = frame_index / self._video_info[0]["fps"]
            timestamp1 = frame_index / self._video_info[1]["fps"]
            self._timing.append(
                {
                    "target_frame_index": float(target),
                    "frame_index": float(frame_index),
                    "timestamp0_s": timestamp0,
                    "timestamp1_s": timestamp1,
                    "nominal_timestamp_difference_s": abs(
                        timestamp0 - timestamp1
                    ),
                }
            )
        self._sample_cursor += 1
        if self._sample_cursor >= len(self._sample_targets):
            self.stage = "rig_solve"
        return CalibrationEvent(
            stage="video_samples",
            status="ACCEPT" if review.accepted else "REJECT",
            progress=0.9
            * self._sample_cursor
            / float(len(self._sample_targets)),
            message=review.reason,
            diagnostics=history,
        )

    def _step_solve(self) -> CalibrationEvent:
        if len(self._samples) < 2:
            raise RuntimeError(
                "at least two quality-approved video samples are required"
            )
        started = time.perf_counter()
        rotation, diagnostics = solve_rig_samples(
            self.intrinsics.camera0,
            self.intrinsics.camera1,
            self._samples,
            self._timing,
            self.config,
            matched_points=self._accepted_matches,
        )
        solve_seconds = time.perf_counter() - started
        diagnostics["video_sampling"] = {
            "pairing": "same frame index",
            "videos": self._video_info,
            "requested_frame_indices": list(self._sample_targets),
            "accepted_frame_indices": list(self.sample_indices),
            "stability_check_enabled": self.check_stability,
            "stable_frames_required": self.config.stable_frames,
            "motion_threshold": self.config.motion_threshold,
            "stability_search_frames": self.stability_search_frames,
            "review_history": self._review_history,
        }
        diagnostics["performance"] = {
            "review_seconds": self._review_seconds,
            "solve_seconds": solve_seconds,
            "total_algorithm_seconds": self._review_seconds + solve_seconds,
        }
        self._diagnostics["rig"] = diagnostics
        self._result = CalibrationProfile(
            self.intrinsics.camera0,
            self.intrinsics.camera1,
            rotation,
        )
        self.state = PipelineState.COMPLETED
        self.stage = "complete"
        self._cleanup()
        return CalibrationEvent(
            stage="complete",
            status="COMPLETE",
            progress=1.0,
            message="video rig calibration complete",
            diagnostics=diagnostics,
        )

    def step(self) -> Optional[CalibrationEvent]:
        if self.state == PipelineState.COMPLETED:
            return None
        if self.state == PipelineState.CANCELLED:
            raise OperationCancelled("video rig calibration was cancelled")
        if self.state != PipelineState.RUNNING:
            raise InvalidStateError(
                "VideoRigCalibrationSession must be running before step"
            )
        try:
            if self.stage == "video_samples":
                return self._step_sample()
            if self.stage == "rig_solve":
                return self._step_solve()
            raise InvalidStateError(
                "unknown video rig calibration stage {!r}".format(self.stage)
            )
        except Exception:
            self.state = PipelineState.FAILED
            self._cleanup()
            raise

    def events(self) -> Iterator[CalibrationEvent]:
        while self.state == PipelineState.RUNNING:
            event = self.step()
            if event is not None:
                yield event

    def run(self) -> CalibrationProfile:
        if self.state != PipelineState.RUNNING:
            self.start()
        for _ in self.events():
            pass
        return self.result

    def save(self, path: Optional[PathLike] = None) -> Path:
        output = Path(path) if path is not None else self.calibration_path
        if output is None:
            raise InvalidStateError(
                "a calibration-result path is required for this session"
            )
        return update_calibration_profile(
            output,
            self.result,
            diagnostics=self._diagnostics,
        )

    def cancel(self) -> None:
        if self.state == PipelineState.RUNNING:
            self.state = PipelineState.CANCELLED
            self._cleanup()

    def stop(self) -> None:
        self._cleanup()
        if self.state == PipelineState.RUNNING:
            self.state = PipelineState.STOPPED

    def _cleanup(self) -> None:
        if self._captures is not None:
            for capture in self._captures:
                capture.release()
            self._captures = None
        self._reviewer = None

    def __enter__(self) -> "VideoRigCalibrationSession":
        return self.start()

    def __exit__(self, *args: Any) -> None:
        self.stop()


__all__ = ["VideoRigCalibrationSession"]
