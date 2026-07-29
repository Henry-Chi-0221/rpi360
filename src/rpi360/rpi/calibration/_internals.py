"""Intrinsic and relative-rotation calibration for an RPI360 rig."""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

import cv2
import numpy as np

from ...common.types import (
    CameraCalibration,
    orthonormalized_rotation,
)
from ...common.rendering import (
    equirectangular_pixels_to_unit_rays,
    project_unit_rays_to_fisheye,
)


def _as_calibration_points(
    object_points: Sequence[np.ndarray],
    image_points: Sequence[np.ndarray],
) -> Tuple[List[np.ndarray], List[np.ndarray]]:
    if len(object_points) != len(image_points) or len(object_points) < 3:
        raise ValueError("at least three matched calibration observations are required")
    objects: List[np.ndarray] = []
    images: List[np.ndarray] = []
    for object_set, image_set in zip(object_points, image_points):
        object_array = np.asarray(object_set, dtype=np.float64).reshape(-1, 1, 3)
        image_array = np.asarray(image_set, dtype=np.float64).reshape(-1, 1, 2)
        if len(object_array) != len(image_array) or len(object_array) < 4:
            raise ValueError(
                "each calibration view needs at least four object/image points"
            )
        objects.append(object_array)
        images.append(image_array)
    return objects, images


def calibrate_intrinsics(
    object_points: Sequence[np.ndarray],
    image_points: Sequence[np.ndarray],
    image_size: Tuple[int, int],
    *,
    calibration_flags: Optional[int] = None,
) -> Tuple[CameraCalibration, float]:
    """Calibrate one OpenCV fisheye camera from point observations.

    ``image_size`` follows OpenCV's ``(width, height)`` order. The returned
    RMS value is useful for rejecting poor checkerboard datasets.
    """
    objects, images = _as_calibration_points(object_points, image_points)
    width, height = map(int, image_size)
    if width <= 0 or height <= 0:
        raise ValueError("image_size must contain positive width and height")
    if calibration_flags is None:
        calibration_flags = (
            cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC
            | cv2.fisheye.CALIB_CHECK_COND
            | cv2.fisheye.CALIB_FIX_SKEW
        )

    K = np.array(
        [
            [max(width, height) / np.pi, 0.0, width / 2.0],
            [0.0, max(width, height) / np.pi, height / 2.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    D = np.zeros((4, 1), dtype=np.float64)
    rms, K, D, _, _ = cv2.fisheye.calibrate(
        objects,
        images,
        (width, height),
        K,
        D,
        None,
        None,
        flags=int(calibration_flags),
        criteria=(
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER,
            200,
            1e-8,
        ),
    )
    return CameraCalibration(width, height, K, D.reshape(4)), float(rms)


def calibrate_intrinsics_camera0(
    object_points: Sequence[np.ndarray],
    image_points: Sequence[np.ndarray],
    image_size: Tuple[int, int],
    **kwargs: Any,
) -> Tuple[CameraCalibration, float]:
    return calibrate_intrinsics(object_points, image_points, image_size, **kwargs)


def calibrate_intrinsics_camera1(
    object_points: Sequence[np.ndarray],
    image_points: Sequence[np.ndarray],
    image_size: Tuple[int, int],
    **kwargs: Any,
) -> Tuple[CameraCalibration, float]:
    return calibrate_intrinsics(object_points, image_points, image_size, **kwargs)


def fisheye_pixels_to_unit_rays(
    pixels: np.ndarray,
    calibration: CameraCalibration,
    *,
    image_size: Optional[Tuple[int, int]] = None,
    iterations: int = 12,
) -> np.ndarray:
    """Invert the OpenCV fisheye polynomial with Newton iterations."""
    points = np.asarray(pixels, dtype=np.float64).reshape(-1, 2)
    if image_size is None:
        width, height = calibration.width, calibration.height
    else:
        width, height = map(int, image_size)
    K = calibration.scaled_K(width, height)

    normalized_y = (points[:, 1] - K[1, 2]) / K[1, 1]
    normalized_x = (points[:, 0] - K[0, 2] - K[0, 1] * normalized_y) / K[0, 0]
    radius_distorted = np.sqrt(
        normalized_x * normalized_x + normalized_y * normalized_y
    )

    theta = radius_distorted.copy()
    k1, k2, k3, k4 = calibration.D
    for _ in range(int(iterations)):
        theta2 = theta * theta
        polynomial = (
            1.0 + k1 * theta2 + k2 * theta2**2 + k3 * theta2**3 + k4 * theta2**4
        )
        function = theta * polynomial - radius_distorted
        derivative = (
            1.0
            + 3.0 * k1 * theta2
            + 5.0 * k2 * theta2**2
            + 7.0 * k3 * theta2**3
            + 9.0 * k4 * theta2**4
        )
        theta -= np.divide(
            function,
            derivative,
            out=np.zeros_like(theta),
            where=np.abs(derivative) > 1e-12,
        )
    theta = np.clip(theta, 0.0, np.pi)

    azimuth_x = np.divide(
        normalized_x,
        radius_distorted,
        out=np.ones_like(normalized_x),
        where=radius_distorted > 1e-12,
    )
    azimuth_y = np.divide(
        normalized_y,
        radius_distorted,
        out=np.zeros_like(normalized_y),
        where=radius_distorted > 1e-12,
    )
    sin_theta = np.sin(theta)
    rays = np.stack(
        (
            sin_theta * azimuth_x,
            -sin_theta * azimuth_y,
            np.cos(theta),
        ),
        axis=1,
    )
    return rays / np.maximum(np.linalg.norm(rays, axis=1, keepdims=True), 1e-12)


def solve_rotation_svd(rays_cam1: np.ndarray, rays_cam0: np.ndarray) -> np.ndarray:
    """Solve ``ray_cam0 ~= R_cam1_to_cam0 @ ray_cam1`` with Kabsch SVD."""
    source = np.array(rays_cam1, dtype=np.float64, copy=True).reshape(-1, 3)
    destination = np.array(rays_cam0, dtype=np.float64, copy=True).reshape(-1, 3)
    if len(source) != len(destination) or len(source) < 3:
        raise ValueError("at least three paired rays are required")
    source /= np.maximum(np.linalg.norm(source, axis=1, keepdims=True), 1e-12)
    destination /= np.maximum(np.linalg.norm(destination, axis=1, keepdims=True), 1e-12)

    cross_covariance = source.T @ destination
    u, _, vt = np.linalg.svd(cross_covariance)
    row_rotation = u @ vt
    if np.linalg.det(row_rotation) < 0.0:
        u[:, -1] *= -1.0
        row_rotation = u @ vt
    return orthonormalized_rotation(row_rotation.T)


def _rotation_errors_deg(
    rotation: np.ndarray, rays_cam1: np.ndarray, rays_cam0: np.ndarray
) -> np.ndarray:
    predicted = np.asarray(rays_cam1, dtype=np.float64) @ rotation.T
    predicted /= np.maximum(np.linalg.norm(predicted, axis=1, keepdims=True), 1e-12)
    destination = np.array(rays_cam0, dtype=np.float64, copy=True)
    destination /= np.maximum(np.linalg.norm(destination, axis=1, keepdims=True), 1e-12)
    cosine = np.clip(np.sum(predicted * destination, axis=1), -1.0, 1.0)
    return np.rad2deg(np.arccos(cosine))


def calibrate_rig_rotation(
    camera0_points_or_rays: np.ndarray,
    camera1_points_or_rays: np.ndarray,
    camera0: Optional[CameraCalibration] = None,
    camera1: Optional[CameraCalibration] = None,
    *,
    ransac_threshold_deg: float = 0.4,
    ransac_iterations: int = 5000,
    random_seed: int = 0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Estimate camera 1 -> camera 0 rotation with the reference rig solver.

    Pass ``camera0`` and ``camera1`` when the inputs are Nx2 fisheye pixels.
    Without calibrations, inputs must already be Nx3 unit rays.

    The estimator intentionally follows
    the validated reference equirectangular SIFT estimator:
    four-ray RANSAC hypotheses, angular-RMSE tie breaking, and iterative
    Kabsch/SVD inlier refinement until convergence (at most eight passes).
    """
    points0 = np.asarray(camera0_points_or_rays, dtype=np.float64)
    points1 = np.asarray(camera1_points_or_rays, dtype=np.float64)
    if camera0 is None and camera1 is None:
        rays0 = points0.reshape(-1, 3)
        rays1 = points1.reshape(-1, 3)
    elif camera0 is not None and camera1 is not None:
        rays0 = fisheye_pixels_to_unit_rays(points0, camera0)
        rays1 = fisheye_pixels_to_unit_rays(points1, camera1)
    else:
        raise ValueError("camera0 and camera1 calibrations must be supplied together")
    if len(rays0) != len(rays1) or len(rays0) < 4:
        raise ValueError("at least four paired camera correspondences are required")
    if not 0.0 < ransac_threshold_deg < 180.0:
        raise ValueError("ransac_threshold_deg must be between 0 and 180")

    generator = np.random.default_rng(random_seed)
    best_mask: Optional[np.ndarray] = None
    best_rotation: Optional[np.ndarray] = None
    best_count = -1
    best_rmse = float("inf")
    sample_size = min(4, len(rays0))
    for _ in range(max(1, int(ransac_iterations))):
        sample = generator.choice(len(rays0), sample_size, replace=False)
        try:
            candidate = solve_rotation_svd(rays1[sample], rays0[sample])
        except np.linalg.LinAlgError:
            continue
        errors = _rotation_errors_deg(candidate, rays1, rays0)
        mask = errors < ransac_threshold_deg
        count = int(np.count_nonzero(mask))
        rmse = (
            float(np.sqrt(np.mean(errors[mask] ** 2)))
            if count
            else float("inf")
        )
        if count > best_count or (count == best_count and rmse < best_rmse):
            best_count = count
            best_rmse = rmse
            best_rotation = candidate
            best_mask = mask

    if best_mask is None or best_count < 4:
        raise RuntimeError("RANSAC failed: best inliers={}".format(best_count))

    mask = best_mask.copy()
    for _ in range(8):
        best_rotation = solve_rotation_svd(rays1[mask], rays0[mask])
        errors = _rotation_errors_deg(best_rotation, rays1, rays0)
        new_mask = errors < ransac_threshold_deg
        if np.count_nonzero(new_mask) < 4 or np.array_equal(new_mask, mask):
            break
        mask = new_mask
    best_rotation = solve_rotation_svd(rays1[mask], rays0[mask])
    errors = _rotation_errors_deg(best_rotation, rays1, rays0)
    return best_rotation, mask, errors


def _equirectangular_points_to_rays(
    points: np.ndarray, width: int, height: int
) -> np.ndarray:
    """Exact equi pixel-to-row-ray conversion from the RPi reference."""
    points = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    longitude = (points[:, 0] / (width / 2.0) - 1.0) * np.pi
    latitude = (points[:, 1] / height - 0.5) * np.pi
    cos_latitude = np.cos(latitude)
    return np.stack(
        (
            cos_latitude * np.sin(longitude),
            np.sin(latitude),
            cos_latitude * np.cos(longitude),
        ),
        axis=1,
    )


# ============================================================================
# Interactive Raspberry Pi calibration
# ============================================================================


@dataclass(frozen=True)
class IntrinsicGuideStage:
    name: str
    instruction: str
    tilt_hint: str
    target_height_radius: float
    area_min: float
    area_max: float
    max_center_error_ratio: float


DEFAULT_INTRINSIC_GUIDE_STAGES: Tuple[IntrinsicGuideStage, ...] = (
    IntrinsicGuideStage(
        "CENTER_FAR",
        "Keep the board centered and move it farther away.",
        "Keep it approximately front-facing.",
        0.34,
        0.025,
        0.090,
        0.22,
    ),
    IntrinsicGuideStage(
        "CENTER_MEDIUM",
        "Keep the board centered and move it closer.",
        "Keep it approximately front-facing.",
        0.50,
        0.070,
        0.180,
        0.20,
    ),
    IntrinsicGuideStage(
        "CENTER_NEAR",
        "Keep the board centered and move it closer again.",
        "Keep it approximately front-facing.",
        0.70,
        0.150,
        0.360,
        0.18,
    ),
    IntrinsicGuideStage(
        "CENTER_LEFT_TILT",
        "Keep the board centered at medium distance.",
        "Tilt or rotate it slightly toward the left.",
        0.54,
        0.070,
        0.210,
        0.20,
    ),
    IntrinsicGuideStage(
        "CENTER_RIGHT_TILT",
        "Keep the board centered at medium distance.",
        "Tilt or rotate it slightly toward the right.",
        0.54,
        0.070,
        0.210,
        0.20,
    ),
    IntrinsicGuideStage(
        "CENTER_UP_TILT",
        "Keep the board centered at medium distance.",
        "Tilt its top edge away from the camera.",
        0.54,
        0.070,
        0.210,
        0.20,
    ),
    IntrinsicGuideStage(
        "CENTER_DOWN_TILT",
        "Keep the board centered at medium distance.",
        "Tilt its bottom edge away from the camera.",
        0.54,
        0.070,
        0.210,
        0.20,
    ),
    IntrinsicGuideStage(
        "CENTER_DIAGONAL_TILT",
        "Keep the board centered at medium-to-near distance.",
        "Rotate it diagonally and add a small tilt.",
        0.62,
        0.100,
        0.280,
        0.18,
    ),
)


@dataclass(frozen=True)
class InteractiveIntrinsicConfig:
    """Tunable policy for one live fisheye intrinsic calibration."""

    width: int = 1640
    height: int = 1232
    fps: float = 21.0
    fisheye_fov_deg: float = 210.0
    checkerboard: Tuple[int, int] = (9, 6)
    square_size: float = 1.0
    target_samples: int = 30
    coverage_target: float = 0.65
    maximum_samples: int = 100
    maximum_reprojection_error_px: float = 1.0
    minimum_board_area_ratio: float = 0.01
    motion_threshold: float = 3.0
    stable_frames: int = 6
    motion_resize_width: int = 320
    coverage_mask_width: int = 400
    sensor_mode: str = ""
    guide_stages: Tuple[IntrinsicGuideStage, ...] = DEFAULT_INTRINSIC_GUIDE_STAGES

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0 or self.fps <= 0:
            raise ValueError(
                "intrinsic capture width, height, and fps must be positive"
            )
        if not 0.0 < self.fisheye_fov_deg <= 360.0:
            raise ValueError("fisheye_fov_deg must be in (0, 360]")
        if self.checkerboard[0] <= 1 or self.checkerboard[1] <= 1:
            raise ValueError("checkerboard must contain at least 2x2 inner corners")
        if self.square_size <= 0.0:
            raise ValueError("checkerboard square_size must be positive")
        if self.target_samples < max(3, len(self.guide_stages)):
            raise ValueError(
                "target_samples must cover every guide stage and be at least 3"
            )
        if not 0.0 < self.coverage_target <= 1.0:
            raise ValueError("coverage_target must be in (0, 1]")
        if self.maximum_samples < self.target_samples:
            raise ValueError("maximum_samples must be >= target_samples")
        if self.maximum_reprojection_error_px <= 0.0:
            raise ValueError("maximum_reprojection_error_px must be positive")


@dataclass(frozen=True)
class InteractiveRigConfig:
    """Live multi-frame SIFT policy for camera 1 -> camera 0 rotation."""

    width: int = 1640
    height: int = 1232
    fps: float = 21.0
    capture_seconds: float = 20.0
    sample_count: int = 10
    manual_capture: bool = False
    maximum_sync_difference_us: float = 50_000.0
    strict_sync: bool = False
    equirectangular_width: int = 0
    equirectangular_height: int = 0
    feature_scale: float = 1.0
    nfeatures: int = 12_000
    sift_contrast_threshold: float = 0.02
    clahe_clip_limit: float = 0.0
    clahe_tile_grid_size: Tuple[int, int] = (16, 8)
    ratio_threshold: float = 0.68
    mutual_matching: bool = True
    latitude_limit_deg: float = 60.0
    mask_erode_pixels: int = 5
    ransac_threshold_deg: float = 0.4
    ransac_iterations: int = 5000
    minimum_inliers: int = 12
    minimum_inlier_ratio: float = 0.15
    motion_threshold: float = 3.0
    stable_frames: int = 6
    motion_resize_width: int = 320
    sample_review_interval_seconds: float = 0.5
    minimum_keypoints_per_camera: int = 40
    minimum_matches_per_sample: int = 12
    minimum_sample_inliers: int = 8
    minimum_sample_inlier_ratio: float = 0.25
    maximum_sample_reprojection_error_px: float = 8.0
    sample_ransac_iterations: int = 5000

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0 or self.fps <= 0:
            raise ValueError("rig capture width, height, and fps must be positive")
        if self.capture_seconds <= 0.0 or self.sample_count < 2:
            raise ValueError("capture_seconds must be positive and sample_count >= 2")
        if self.equirectangular_width == 0 and self.equirectangular_height == 0:
            reference_width = int(self.width * np.pi)
            object.__setattr__(self, "equirectangular_width", reference_width)
            object.__setattr__(
                self,
                "equirectangular_height",
                reference_width // 2,
            )
        elif self.equirectangular_width <= 0 or self.equirectangular_height <= 0:
            raise ValueError(
                "equirectangular dimensions must both be positive or both be zero"
            )
        if not 0.0 < self.feature_scale <= 1.0:
            raise ValueError("feature_scale must be in (0, 1]")
        if self.sift_contrast_threshold <= 0.0:
            raise ValueError("sift_contrast_threshold must be positive")
        if self.clahe_clip_limit < 0.0:
            raise ValueError("clahe_clip_limit must be non-negative")
        if (
            len(self.clahe_tile_grid_size) != 2
            or min(self.clahe_tile_grid_size) < 1
        ):
            raise ValueError("clahe_tile_grid_size must contain two positive values")
        if not 0.0 < self.ratio_threshold < 1.0:
            raise ValueError("ratio_threshold must be in (0, 1)")
        if not 0.0 < self.ransac_threshold_deg < 180.0:
            raise ValueError("ransac_threshold_deg must be between 0 and 180")
        if not 0.0 <= self.minimum_inlier_ratio <= 1.0:
            raise ValueError("minimum_inlier_ratio must be in [0, 1]")
        if self.motion_threshold <= 0.0:
            raise ValueError("motion_threshold must be positive")
        if self.stable_frames < 1 or self.motion_resize_width < 1:
            raise ValueError("stable_frames and motion_resize_width must be positive")
        if self.sample_review_interval_seconds < 0.0:
            raise ValueError("sample_review_interval_seconds must be non-negative")
        if self.minimum_keypoints_per_camera < 4:
            raise ValueError("minimum_keypoints_per_camera must be >= 4")
        if self.minimum_matches_per_sample < 4:
            raise ValueError("minimum_matches_per_sample must be >= 4")
        if self.minimum_sample_inliers < 3:
            raise ValueError("minimum_sample_inliers must be >= 3")
        if not 0.0 <= self.minimum_sample_inlier_ratio <= 1.0:
            raise ValueError("minimum_sample_inlier_ratio must be in [0, 1]")
        if self.maximum_sample_reprojection_error_px <= 0.0:
            raise ValueError("maximum_sample_reprojection_error_px must be positive")
        if self.sample_ransac_iterations < 1:
            raise ValueError("sample_ransac_iterations must be positive")


class _MotionDetector:
    def __init__(self, config: InteractiveIntrinsicConfig) -> None:
        self.threshold = float(config.motion_threshold)
        self.stable_frames = int(config.stable_frames)
        self.resize_width = int(config.motion_resize_width)
        self.previous: Optional[np.ndarray] = None
        self.still_count = 0
        self.score = float("inf")

    def update(self, gray: np.ndarray) -> Dict[str, Any]:
        height, width = gray.shape[:2]
        if width > self.resize_width:
            scale = self.resize_width / float(width)
            gray = cv2.resize(
                gray,
                (self.resize_width, max(1, int(round(height * scale)))),
                interpolation=cv2.INTER_AREA,
            )
        current = cv2.GaussianBlur(gray, (5, 5), 0)
        if self.previous is None:
            moving = True
        else:
            self.score = float(np.mean(cv2.absdiff(current, self.previous)))
            moving = self.score > self.threshold
        self.still_count = 0 if moving else self.still_count + 1
        self.previous = current
        return {
            "score": self.score,
            "moving": moving,
            "static": self.still_count >= self.stable_frames,
            "still_count": self.still_count,
        }


class _CoverageTracker:
    def __init__(self, width: int, height: int, mask_width: int) -> None:
        self.width = int(width)
        self.height = int(height)
        self.mask_width = int(mask_width)
        self.scale = self.mask_width / float(self.width)
        self.mask_height = max(1, int(round(self.height * self.scale)))
        self.mask = np.zeros((self.mask_height, self.mask_width), dtype=np.uint8)
        radius = min(self.width, self.height) * 0.5
        self.denominator = max(np.pi * radius * radius, 1.0)

    def update(self, corners: np.ndarray) -> None:
        points = corners.reshape(-1, 2).astype(np.float32) * self.scale
        cv2.fillConvexPoly(self.mask, cv2.convexHull(points.astype(np.int32)), 255)

    def ratio(self) -> float:
        covered = np.count_nonzero(self.mask) / (self.scale * self.scale)
        return min(float(covered) / self.denominator, 1.0)

    def full_mask(self) -> np.ndarray:
        return cv2.resize(
            self.mask, (self.width, self.height), interpolation=cv2.INTER_NEAREST
        )


def _find_checkerboard(
    gray: np.ndarray, checkerboard: Tuple[int, int]
) -> Optional[np.ndarray]:
    expected = checkerboard[0] * checkerboard[1]
    if hasattr(cv2, "findChessboardCornersSB"):
        found, corners = cv2.findChessboardCornersSB(
            gray,
            checkerboard,
            cv2.CALIB_CB_NORMALIZE_IMAGE
            | cv2.CALIB_CB_EXHAUSTIVE
            | cv2.CALIB_CB_ACCURACY,
        )
        if found and corners is not None and len(corners) == expected:
            return corners.astype(np.float64)
    found, corners = cv2.findChessboardCorners(
        gray,
        checkerboard,
        cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE,
    )
    if not found or corners is None or len(corners) != expected:
        return None
    return cv2.cornerSubPix(
        gray,
        corners,
        (11, 11),
        (-1, -1),
        (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 40, 1e-3),
    ).astype(np.float64)


def _object_point_template(
    checkerboard: Tuple[int, int], square_size: float
) -> np.ndarray:
    columns, rows = checkerboard
    points = np.zeros((1, columns * rows, 3), dtype=np.float64)
    points[0, :, :2] = np.mgrid[0:columns, 0:rows].T.reshape(-1, 2) * float(square_size)
    return points


def _board_geometry(
    corners: np.ndarray, width: int, height: int
) -> Tuple[np.ndarray, np.ndarray, float, float]:
    hull = cv2.convexHull(corners.reshape(-1, 2).astype(np.float32))
    moments = cv2.moments(hull)
    if abs(moments["m00"]) < 1e-9:
        center = hull.reshape(-1, 2).mean(axis=0)
    else:
        center = np.array(
            [moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]]
        )
    radius = min(width, height) * 0.5
    center_error = float(
        np.linalg.norm(center - np.array([width * 0.5, height * 0.5]))
        / max(radius, 1e-9)
    )
    area_ratio = float(abs(cv2.contourArea(hull))) / max(np.pi * radius * radius, 1.0)
    return hull, center, center_error, area_ratio


def _reprojection_errors(
    object_points: Sequence[np.ndarray],
    image_points: Sequence[np.ndarray],
    rvecs: Sequence[np.ndarray],
    tvecs: Sequence[np.ndarray],
    K: np.ndarray,
    D: np.ndarray,
) -> np.ndarray:
    errors = []
    for objects, observed, rvec, tvec in zip(object_points, image_points, rvecs, tvecs):
        projected, _ = cv2.fisheye.projectPoints(objects, rvec, tvec, K, D)
        delta = observed.reshape(-1, 2) - projected.reshape(-1, 2)
        errors.append(float(np.sqrt(np.mean(np.sum(delta * delta, axis=1)))))
    return np.asarray(errors, dtype=np.float64)


def _solve_guided_intrinsics(
    corners: Sequence[np.ndarray],
    config: InteractiveIntrinsicConfig,
    previous: Optional[Mapping[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], str]:
    if len(corners) < 2:
        return None, "collecting initial guide poses"
    objects = [
        _object_point_template(config.checkerboard, config.square_size) for _ in corners
    ]
    images = [
        np.asarray(value, dtype=np.float64).reshape(-1, 1, 2) for value in corners
    ]
    image_size = (config.width, config.height)
    flags = (
        cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC
        | cv2.fisheye.CALIB_FIX_SKEW
        | cv2.fisheye.CALIB_USE_INTRINSIC_GUESS
    )
    criteria = (
        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER,
        150,
        1e-6,
    )
    initializations: List[Tuple[str, np.ndarray, np.ndarray]] = []
    if previous is not None:
        initializations.append(
            ("previous K/D", previous["K"].copy(), previous["D"].copy())
        )
    for focal_scale in (0.35, 0.50, 0.70, 1.00):
        focal = max(image_size) * focal_scale
        initializations.append(
            (
                f"focal={focal:.0f}",
                np.array(
                    [
                        [focal, 0.0, config.width * 0.5],
                        [0.0, focal, config.height * 0.5],
                        [0.0, 0.0, 1.0],
                    ],
                    dtype=np.float64,
                ),
                np.zeros((4, 1), dtype=np.float64),
            )
        )

    best: Optional[Dict[str, Any]] = None
    failures = []
    for label, K0, D0 in initializations:
        try:
            rms, K, D, rvecs, tvecs = cv2.fisheye.calibrate(
                objects,
                images,
                image_size,
                K0,
                D0,
                None,
                None,
                flags=flags,
                criteria=criteria,
            )
        except cv2.error as exc:
            failures.append(f"{label}: {str(exc).splitlines()[0]}")
            continue
        errors = _reprojection_errors(objects, images, rvecs, tvecs, K, D)
        focal_is_sane = 0.05 * min(image_size) <= K[0, 0] <= 10.0 * max(
            image_size
        ) and 0.05 * min(image_size) <= K[1, 1] <= 10.0 * max(image_size)
        if (
            not focal_is_sane
            or not np.all(np.isfinite(K))
            or not np.all(np.isfinite(D))
            or not np.all(np.isfinite(errors))
            or float(np.max(np.abs(D))) > 1e4
        ):
            failures.append(f"{label}: numerically invalid calibration")
            continue
        result = {
            "rms": float(rms),
            "K": K,
            "D": D,
            "per_sample_errors": errors,
            "initialization": label,
        }
        if best is None or float(errors.mean()) < float(
            best["per_sample_errors"].mean()
        ):
            best = result
    return best, "" if best is not None else "; ".join(failures[-3:])


def _guide_rectangles(
    stage: IntrinsicGuideStage, width: int, height: int
) -> Tuple[np.ndarray, np.ndarray]:
    radius = min(width, height) * 0.5
    target_height = stage.target_height_radius * radius
    target_width = target_height * 1.6

    def rectangle(scale: float) -> np.ndarray:
        half_width = target_width * scale * 0.5
        half_height = target_height * scale * 0.5
        center_x, center_y = width * 0.5, height * 0.5
        return np.array(
            [
                [center_x - half_width, center_y - half_height],
                [center_x + half_width, center_y - half_height],
                [center_x + half_width, center_y + half_height],
                [center_x - half_width, center_y + half_height],
            ],
            dtype=np.int32,
        ).reshape(-1, 1, 2)

    return rectangle(1.0), rectangle(1.45)


def _draw_intrinsic_preview(
    frame: np.ndarray,
    *,
    corners: Optional[np.ndarray],
    coverage: _CoverageTracker,
    stage: Optional[IntrinsicGuideStage],
    status: str,
    reason: str,
    accepted_count: int,
    config: InteractiveIntrinsicConfig,
    motion: Mapping[str, Any],
    latest_result: Optional[Mapping[str, Any]],
) -> np.ndarray:
    preview = frame.copy()
    coverage_mask = coverage.full_mask() > 0
    green = np.zeros_like(preview)
    green[:, :, 1] = 255
    tinted = cv2.addWeighted(preview, 0.72, green, 0.28, 0.0)
    preview[coverage_mask] = tinted[coverage_mask]
    if stage is not None:
        ideal, allowed = _guide_rectangles(stage, config.width, config.height)
        cv2.polylines(preview, [allowed], True, (0, 170, 255), 3, cv2.LINE_AA)
        cv2.polylines(preview, [ideal], True, (255, 255, 0), 3, cv2.LINE_AA)
    if corners is not None:
        hull = cv2.convexHull(corners.reshape(-1, 2).astype(np.float32)).astype(
            np.int32
        )
        cv2.polylines(preview, [hull], True, (0, 255, 0), 4, cv2.LINE_AA)
        cv2.drawChessboardCorners(
            preview, config.checkerboard, corners.astype(np.float32), True
        )
    cv2.drawMarker(
        preview,
        (config.width // 2, config.height // 2),
        (255, 255, 255),
        cv2.MARKER_CROSS,
        35,
        2,
    )

    panel_height = 190
    panel = np.zeros((panel_height, config.width, 3), dtype=np.uint8)
    coverage_ratio = coverage.ratio()
    progress = min(
        accepted_count / float(config.target_samples),
        coverage_ratio / config.coverage_target,
    )
    error_text = "not solved yet"
    if latest_result is not None:
        errors = latest_result["per_sample_errors"]
        error_text = (
            f"RMS {latest_result['rms']:.3f}px | "
            f"mean {errors.mean():.3f}px | max {errors.max():.3f}px"
        )
    lines = [
        (
            f"{status} | samples {accepted_count}/{config.target_samples} | "
            f"coverage {coverage_ratio * 100:.1f}/{config.coverage_target * 100:.1f}%"
        ),
        reason[:150],
        (
            f"motion {motion['score']:.2f} | still "
            f"{motion['still_count']}/{config.stable_frames} | {error_text}"
        ),
        (
            "Guide: "
            + (
                f"{stage.name} - {stage.instruction} {stage.tilt_hint}"
                if stage is not None
                else "move the board around the uncovered green-free image area"
            )
        )[:160],
        "Pause, capture, and cancel are controlled by the caller.",
    ]
    colors = [
        (60, 230, 60) if status == "ACCEPT" else (255, 255, 255),
        (0, 210, 255),
        (210, 210, 210),
        (255, 230, 120),
        (170, 170, 170),
    ]
    for index, (line, color) in enumerate(zip(lines, colors)):
        cv2.putText(
            panel,
            line,
            (18, 29 + index * 31),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.66,
            color,
            2,
            cv2.LINE_AA,
        )
    x0, x1, y0, y1 = 18, config.width - 18, panel_height - 18, panel_height - 6
    cv2.rectangle(panel, (x0, y0), (x1, y1), (90, 90, 90), -1)
    cv2.rectangle(
        panel,
        (x0, y0),
        (x0 + int(round((x1 - x0) * np.clip(progress, 0.0, 1.0))), y1),
        (40, 210, 80),
        -1,
    )
    return np.vstack((preview, panel))


def _single_camera_equirectangular_geometry(
    calibration: CameraCalibration,
    frame_shape: Tuple[int, ...],
    width: int,
    height: int,
    ray_rotation: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    rays = equirectangular_pixels_to_unit_rays(width, height)
    if ray_rotation is not None:
        rays = rays @ ray_rotation
    map_x, map_y, valid, _ = project_unit_rays_to_fisheye(
        rays, calibration, frame_shape[1], frame_shape[0]
    )
    return map_x, map_y, valid.astype(np.uint8) * 255


def _remap_single_camera_equirectangular(
    frame: np.ndarray,
    geometry: Tuple[np.ndarray, np.ndarray, np.ndarray],
) -> Tuple[np.ndarray, np.ndarray]:
    map_x, map_y, valid = geometry
    image = cv2.remap(
        frame,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    )
    image[valid == 0] = 0
    return image, valid


def _feature_mask(
    valid: np.ndarray, latitude_limit_deg: float, erode_pixels: int
) -> np.ndarray:
    mask = valid.copy()
    if erode_pixels > 0:
        size = 2 * int(erode_pixels) + 1
        mask = cv2.erode(mask, np.ones((size, size), dtype=np.uint8))
    if 0.0 < latitude_limit_deg < 90.0:
        height = mask.shape[0]
        y0 = int(round((0.5 - latitude_limit_deg / 180.0) * height))
        y1 = int(round((0.5 + latitude_limit_deg / 180.0) * height))
        limited = np.zeros_like(mask)
        limited[max(0, y0) : min(height, y1)] = mask[max(0, y0) : min(height, y1)]
        mask = limited
    return mask


class _FeatureMatchError(RuntimeError):
    def __init__(self, message: str, diagnostics: Mapping[str, int]) -> None:
        super().__init__(message)
        self.diagnostics = dict(diagnostics)


def _match_equirectangular_features(
    image0: np.ndarray,
    image1: np.ndarray,
    mask0: np.ndarray,
    mask1: np.ndarray,
    config: InteractiveRigConfig,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    if not hasattr(cv2, "SIFT_create"):
        raise RuntimeError("this OpenCV build does not provide SIFT")
    scale = config.feature_scale
    gray0 = cv2.cvtColor(image0, cv2.COLOR_BGR2GRAY)
    gray1 = cv2.cvtColor(image1, cv2.COLOR_BGR2GRAY)
    if config.clahe_clip_limit > 0.0:
        clahe = cv2.createCLAHE(
            clipLimit=float(config.clahe_clip_limit),
            tileGridSize=tuple(map(int, config.clahe_tile_grid_size)),
        )
        gray0 = clahe.apply(gray0)
        gray1 = clahe.apply(gray1)
    if scale != 1.0:
        gray0 = cv2.resize(
            gray0, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
        )
        gray1 = cv2.resize(
            gray1, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
        )
        mask0 = cv2.resize(
            mask0, (gray0.shape[1], gray0.shape[0]), interpolation=cv2.INTER_NEAREST
        )
        mask1 = cv2.resize(
            mask1, (gray1.shape[1], gray1.shape[0]), interpolation=cv2.INTER_NEAREST
        )
    sift = cv2.SIFT_create(
        nfeatures=int(config.nfeatures),
        contrastThreshold=float(config.sift_contrast_threshold),
        edgeThreshold=10.0,
    )
    keypoints0, descriptors0 = sift.detectAndCompute(gray0, mask0)
    keypoints1, descriptors1 = sift.detectAndCompute(gray1, mask1)
    match_info = {
        "keypoints0": len(keypoints0),
        "keypoints1": len(keypoints1),
        "matches": 0,
        "sift_contrast_threshold": config.sift_contrast_threshold,
        "clahe_clip_limit": config.clahe_clip_limit,
    }
    if descriptors0 is None or descriptors1 is None:
        raise _FeatureMatchError(
            "SIFT found no descriptors in one or both cameras",
            match_info,
        )
    if (
        len(keypoints0) < config.minimum_keypoints_per_camera
        or len(keypoints1) < config.minimum_keypoints_per_camera
    ):
        raise _FeatureMatchError(
            "not enough SIFT keypoints: cam0={} cam1={} (minimum {})".format(
                len(keypoints0),
                len(keypoints1),
                config.minimum_keypoints_per_camera,
            ),
            match_info,
        )

    matcher = cv2.BFMatcher(cv2.NORM_L2)

    def ratio_matches(first: np.ndarray, second: np.ndarray) -> List[cv2.DMatch]:
        matches = []
        for pair in matcher.knnMatch(first, second, k=2):
            if (
                len(pair) == 2
                and pair[0].distance < config.ratio_threshold * pair[1].distance
            ):
                matches.append(pair[0])
        return matches

    forward = ratio_matches(descriptors0, descriptors1)
    if config.mutual_matching:
        reverse_pairs = {
            (match.trainIdx, match.queryIdx)
            for match in ratio_matches(descriptors1, descriptors0)
        }
        forward = [
            match
            for match in forward
            if (match.queryIdx, match.trainIdx) in reverse_pairs
        ]
    forward.sort(key=lambda match: match.distance)
    used0, used1, unique = set(), set(), []
    for match in forward:
        if match.queryIdx in used0 or match.trainIdx in used1:
            continue
        used0.add(match.queryIdx)
        used1.add(match.trainIdx)
        unique.append(match)
    match_info["matches"] = len(unique)
    required_matches = max(4, config.minimum_matches_per_sample)
    if len(unique) < required_matches:
        raise _FeatureMatchError(
            "only {} reliable SIFT matches survived (minimum {})".format(
                len(unique),
                required_matches,
            ),
            match_info,
        )
    points0 = np.asarray([keypoints0[m.queryIdx].pt for m in unique]) / scale
    points1 = np.asarray([keypoints1[m.trainIdx].pt for m in unique]) / scale
    return (
        points0,
        points1,
        match_info,
    )
