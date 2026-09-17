"""Shared public data structures, errors, and rotation mathematics.

Coordinate convention
---------------------
The renderer follows the proven ``original_src.Mapper`` convention. Rays are
stored as row vectors: ``+x`` points right, ``+y`` points toward the bottom of
an equirectangular image, and ``+z`` points forward.

The rig rotation has one deliberately fixed meaning throughout the project::

    ray_cam0 = R_cam1_to_cam0 @ ray_cam1
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Union

import numpy as np

SUPPORTED_PROJECTIONS = frozenset({"perspective", "stereographic", "equirectangular"})
SUPPORTED_QUALITIES = frozenset({"fast", "balanced", "high"})

PathLike = Union[str, os.PathLike]


class R360Error(RuntimeError):
    """Base error for RPI360 files and runtime operations."""


class MetadataError(R360Error):
    """Raised when RPI360 metadata is missing or invalid."""


class ExternalToolError(R360Error):
    """Raised when an ffmpeg/ffprobe operation fails."""


class InvalidStateError(R360Error):
    """Raised when an operation is invalid for the current session state."""


class UnsupportedOperationError(R360Error):
    """Raised when a source does not support a Player operation."""


class CaptureError(R360Error):
    """Raised when a live camera source stops unexpectedly."""


class CalibrationError(R360Error):
    """Raised when captured samples cannot produce a valid calibration."""


class OperationCancelled(R360Error):
    """Raised when a long-running operation is explicitly cancelled."""


class PipelineState(str, Enum):
    """Lifecycle shared by pipelines and step-driven sessions."""

    NEW = "new"
    RUNNING = "running"
    STOPPED = "stopped"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class PlayerState(str, Enum):
    """Lifecycle exposed by the unified Player API."""

    NEW = "new"
    PLAYING = "playing"
    PAUSED = "paused"
    ENDED = "ended"
    STOPPED = "stopped"
    FAILED = "failed"


class FrameOutput(str, Enum):
    """Named images available from every immutable :class:`PlayerFrame`."""

    VIEW = "view"
    CAMERA0 = "camera0"
    CAMERA1 = "camera1"
    EQUI_1 = "equi_1"
    EQUI_2 = "equi_2"
    EQUI_BLENDED = "equi_blended"


def _readonly_float_array(
    value: Any,
    shape: Optional[Sequence[int]],
    name: str,
) -> np.ndarray:
    array = np.array(value, dtype=np.float64, copy=True)
    if shape is not None and array.shape != tuple(shape):
        raise ValueError(f"{name} must have shape {tuple(shape)}, got {array.shape}")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class CameraCalibration:
    """OpenCV fisheye calibration at a known calibration resolution."""

    width: int
    height: int
    K: np.ndarray
    D: np.ndarray
    fisheye_fov_deg: float = 210.0

    def __post_init__(self) -> None:
        if int(self.width) <= 0 or int(self.height) <= 0:
            raise ValueError("camera calibration width and height must be positive")
        object.__setattr__(self, "width", int(self.width))
        object.__setattr__(self, "height", int(self.height))
        object.__setattr__(self, "K", _readonly_float_array(self.K, (3, 3), "K"))

        distortion = np.array(self.D, dtype=np.float64, copy=True).reshape(-1)
        if distortion.size != 4:
            raise ValueError(
                "D must contain four OpenCV fisheye coefficients, "
                f"got {distortion.size}"
            )
        if not np.all(np.isfinite(distortion)):
            raise ValueError("D must contain only finite values")
        distortion.setflags(write=False)
        object.__setattr__(self, "D", distortion)
        fisheye_fov = float(self.fisheye_fov_deg)
        if not math.isfinite(fisheye_fov) or not 0.0 < fisheye_fov <= 360.0:
            raise ValueError("fisheye_fov_deg must be in (0, 360]")
        object.__setattr__(self, "fisheye_fov_deg", fisheye_fov)

        if self.K[0, 0] <= 0.0 or self.K[1, 1] <= 0.0:
            raise ValueError("K focal lengths must be positive")
        if abs(self.K[2, 2] - 1.0) > 1e-9:
            raise ValueError("K[2, 2] must be 1")

    def scaled_K(self, width: int, height: int) -> np.ndarray:
        """Return intrinsics scaled from calibration size to an input frame."""
        scale_x = float(width) / self.width
        scale_y = float(height) / self.height
        scaled = np.array(self.K, copy=True)
        scaled[0, :] *= scale_x
        scaled[1, :] *= scale_y
        scaled[2, :] = (0.0, 0.0, 1.0)
        return scaled

    def to_dict(self) -> Dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "K": self.K.tolist(),
            "D": self.D.tolist(),
            "fisheye_fov_deg": self.fisheye_fov_deg,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        fallback_width: Optional[int] = None,
        fallback_height: Optional[int] = None,
    ) -> "CameraCalibration":
        width = value.get("width", fallback_width)
        height = value.get("height", fallback_height)
        if width is None or height is None:
            raise MetadataError("camera calibration width/height are missing")
        try:
            return cls(
                width=int(width),
                height=int(height),
                K=value["K"],
                D=value["D"],
                fisheye_fov_deg=float(value.get("fisheye_fov_deg", 210.0)),
            )
        except KeyError as exc:
            raise MetadataError(f"camera calibration is missing {exc.args[0]}") from exc


@dataclass(frozen=True)
class DualCameraIntrinsics:
    """Stage-one calibration result for the two fisheye cameras."""

    camera0: CameraCalibration
    camera1: CameraCalibration

    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_0": self.camera0.to_dict(),
            "camera_1": self.camera1.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DualCameraIntrinsics":
        if not isinstance(value, Mapping):
            raise MetadataError("intrinsics must be a JSON object")
        try:
            return cls(
                CameraCalibration.from_dict(value["camera_0"]),
                CameraCalibration.from_dict(value["camera_1"]),
            )
        except KeyError as exc:
            raise MetadataError("intrinsics require camera_0 and camera_1") from exc


@dataclass(frozen=True)
class CalibrationProfile:
    camera0: CameraCalibration
    camera1: CameraCalibration
    R_cam1_to_cam0: np.ndarray

    def __post_init__(self) -> None:
        if not isinstance(self.camera0, CameraCalibration) or not isinstance(
            self.camera1, CameraCalibration
        ):
            raise TypeError("camera0 and camera1 must be CameraCalibration instances")
        rotation = _readonly_float_array(self.R_cam1_to_cam0, (3, 3), "R_cam1_to_cam0")
        validate_rotation_matrix(rotation)
        object.__setattr__(self, "R_cam1_to_cam0", rotation)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_0": self.camera0.to_dict(),
            "camera_1": self.camera1.to_dict(),
            "R_cam1_to_cam0": self.R_cam1_to_cam0.tolist(),
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        streams: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> "CalibrationProfile":
        try:
            stream0 = (streams or {}).get("camera_0", {})
            stream1 = (streams or {}).get("camera_1", {})
            camera0 = CameraCalibration.from_dict(
                value["camera_0"],
                fallback_width=stream0.get("width"),
                fallback_height=stream0.get("height"),
            )
            camera1 = CameraCalibration.from_dict(
                value["camera_1"],
                fallback_width=stream1.get("width"),
                fallback_height=stream1.get("height"),
            )
            return cls(camera0, camera1, value["R_cam1_to_cam0"])
        except KeyError as exc:
            raise MetadataError(f"calibration is missing {exc.args[0]}") from exc


@dataclass(frozen=True)
class ViewConfig:
    projection: str
    width: int
    height: int
    horizontal_fov_deg: float = 90.0
    quality: str = "balanced"
    pixel_format: str = "bgr24"

    def __post_init__(self) -> None:
        projection = str(self.projection).lower()
        quality = str(self.quality).lower()
        if projection not in SUPPORTED_PROJECTIONS:
            raise ValueError(
                "projection must be one of "
                f"{sorted(SUPPORTED_PROJECTIONS)}, got {projection!r}"
            )
        if quality not in SUPPORTED_QUALITIES:
            raise ValueError(f"quality must be one of {sorted(SUPPORTED_QUALITIES)}")
        if int(self.width) <= 0 or int(self.height) <= 0:
            raise ValueError("view width and height must be positive")
        maximum_fov = 360.0 if projection == "stereographic" else 180.0
        if not 0.0 < float(self.horizontal_fov_deg) < maximum_fov:
            raise ValueError(
                f"horizontal_fov_deg must be between 0 and {maximum_fov:g}"
            )
        if self.pixel_format not in {"bgr24", "bgra"}:
            raise ValueError("pixel_format must be 'bgr24' or 'bgra'")
        object.__setattr__(self, "projection", projection)
        object.__setattr__(self, "quality", quality)
        object.__setattr__(self, "width", int(self.width))
        object.__setattr__(self, "height", int(self.height))


def rotation_matrix_from_euler(
    yaw_deg: float = 0.0,
    pitch_deg: float = 0.0,
    roll_deg: float = 0.0,
) -> np.ndarray:
    """Build the exact row-vector rotation used by ``original_src.Mapper``."""
    angles = np.asarray([yaw_deg, pitch_deg, roll_deg], dtype=np.float64)
    if not np.all(np.isfinite(angles)):
        raise ValueError("rotation angles must be finite")
    yaw, pitch, roll = np.deg2rad((-angles[0], angles[1], angles[2]))
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)

    R_yaw = np.array(
        [[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]],
        dtype=np.float64,
    )
    R_pitch = np.array(
        [[1.0, 0.0, 0.0], [0.0, cp, sp], [0.0, -sp, cp]],
        dtype=np.float64,
    )
    R_roll = np.array(
        [[cr, sr, 0.0], [-sr, cr, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    # Mapper.rotate_vectors: vector @ (Rroll @ Rpitch @ Ryaw).
    return R_roll @ R_pitch @ R_yaw


def orthonormalized_rotation(rotation: np.ndarray) -> np.ndarray:
    """Project a nearly rotational matrix onto SO(3) with SVD."""
    matrix = np.asarray(rotation, dtype=np.float64)
    if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
        raise ValueError("rotation must be a finite 3x3 matrix")
    u, _, vt = np.linalg.svd(matrix)
    result = u @ vt
    if np.linalg.det(result) < 0.0:
        u[:, -1] *= -1.0
        result = u @ vt
    return result


@dataclass
class OrientationState:
    """Accumulated viewer orientation stored as a rotation matrix, not Euler angles."""

    rotation_matrix: np.ndarray = field(
        default_factory=lambda: np.eye(3, dtype=np.float64)
    )
    _updates_since_normalization: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.set_matrix(self.rotation_matrix)

    @classmethod
    def identity(cls) -> "OrientationState":
        return cls(np.eye(3, dtype=np.float64))

    def copy(self) -> "OrientationState":
        return OrientationState(self.rotation_matrix.copy())

    def rotate_local(
        self,
        yaw_delta_deg: float = 0.0,
        pitch_delta_deg: float = 0.0,
        roll_delta_deg: float = 0.0,
    ) -> "OrientationState":
        """Apply the camera-local increment order used by Mapper."""
        delta = rotation_matrix_from_euler(
            yaw_delta_deg, pitch_delta_deg, roll_delta_deg
        )
        self.rotation_matrix = delta @ self.rotation_matrix
        self._after_update()
        return self

    def rotate_world(
        self,
        yaw_delta_deg: float = 0.0,
        pitch_delta_deg: float = 0.0,
        roll_delta_deg: float = 0.0,
    ) -> "OrientationState":
        """Apply an increment around rig/world axes."""
        delta = rotation_matrix_from_euler(
            yaw_delta_deg, pitch_delta_deg, roll_delta_deg
        )
        self.rotation_matrix = self.rotation_matrix @ delta
        self._after_update()
        return self

    def _after_update(self) -> None:
        self._updates_since_normalization += 1
        if self._updates_since_normalization >= 32:
            self.normalize()

    def normalize(self) -> None:
        self.rotation_matrix = orthonormalized_rotation(self.rotation_matrix)
        self._updates_since_normalization = 0

    def reset(self) -> None:
        self.rotation_matrix = np.eye(3, dtype=np.float64)
        self._updates_since_normalization = 0

    def set_matrix(self, rotation: np.ndarray) -> None:
        matrix = np.asarray(rotation, dtype=np.float64)
        validate_rotation_matrix(matrix, atol=1e-5)
        self.rotation_matrix = orthonormalized_rotation(matrix)
        self._updates_since_normalization = 0


@dataclass
class RenderResult:
    image: np.ndarray
    timestamp0: Optional[float] = None
    timestamp1: Optional[float] = None
    sync_error_us: Optional[int] = None
    equirectangular: Optional[np.ndarray] = None


def validate_rotation_matrix(rotation: np.ndarray, atol: float = 1e-5) -> bool:
    matrix = np.asarray(rotation, dtype=np.float64)
    if matrix.shape != (3, 3):
        raise ValueError(f"rotation matrix must have shape (3, 3), got {matrix.shape}")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("rotation matrix must contain only finite values")
    if not np.allclose(matrix.T @ matrix, np.eye(3), atol=atol, rtol=0.0):
        raise ValueError("rotation matrix is not orthonormal")
    determinant = float(np.linalg.det(matrix))
    if not math.isclose(determinant, 1.0, abs_tol=atol):
        raise ValueError(f"rotation matrix determinant must be +1, got {determinant}")
    return True


def validate_calibration(calibration: CalibrationProfile) -> bool:
    if not isinstance(calibration, CalibrationProfile):
        raise TypeError("calibration must be a CalibrationProfile")
    validate_rotation_matrix(calibration.R_cam1_to_cam0)
    return True
