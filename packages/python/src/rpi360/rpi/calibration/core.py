"""Pure calibration mathematics and explicit profile persistence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from ...common.metadata import (
    calibration_document_from_intrinsics,
    calibration_intrinsics_from_document,
    calibration_profile_from_result,
    calibration_result_from_profile,
    load_calibration_document,
    load_calibration_result,
    save_calibration_result,
    update_calibration_document,
)
from ...common.rendering import (
    camera1_mount_rotation,
    unit_rays_to_equirectangular_map,
)
from ...common.types import (
    CalibrationProfile,
    CameraCalibration,
    DualCameraIntrinsics,
    MetadataError,
    PathLike,
    validate_calibration,
)
from ._internals import (
    DEFAULT_INTRINSIC_GUIDE_STAGES,
    InteractiveIntrinsicConfig,
    InteractiveRigConfig,
    IntrinsicGuideStage,
    _equirectangular_points_to_rays,
    _feature_mask,
    _match_equirectangular_features,
    _remap_single_camera_equirectangular,
    _single_camera_equirectangular_geometry,
    calibrate_intrinsics,
    calibrate_intrinsics_camera0,
    calibrate_intrinsics_camera1,
    calibrate_rig_rotation,
    fisheye_pixels_to_unit_rays,
    solve_rotation_svd,
)


@dataclass(frozen=True)
class RigSampleReview:
    """Quality decision and inspectable intermediate values for one frame pair."""

    accepted: bool
    reason: str
    diagnostics: Mapping[str, Any]
    equi0: np.ndarray
    equi1: np.ndarray
    points0: np.ndarray
    points1: np.ndarray
    inliers: np.ndarray
    rotation: Optional[np.ndarray]


def _equirectangular_reprojection_errors(
    rotation_cam1_to_cam0: np.ndarray,
    rays_cam0: np.ndarray,
    points_cam1: np.ndarray,
    width: int,
    height: int,
) -> np.ndarray:
    """Return wrapped pixel residuals using the reference rig convention."""
    # The stored column rotation maps cam1 -> cam0. For row rays the same
    # matrix therefore maps cam0 -> cam1, exactly like pixel_errors_from_R()
    # in the proven RPi reference implementation.
    predicted_rays1 = np.asarray(rays_cam0) @ rotation_cam1_to_cam0
    predicted_x, predicted_y = unit_rays_to_equirectangular_map(
        predicted_rays1,
        width,
        height,
    )
    delta_x = (
        predicted_x.astype(np.float64)
        - np.asarray(points_cam1, dtype=np.float64)[:, 0]
        + width / 2.0
    ) % width - width / 2.0
    delta_y = (
        predicted_y.astype(np.float64)
        - np.asarray(points_cam1, dtype=np.float64)[:, 1]
    )
    return np.sqrt(delta_x * delta_x + delta_y * delta_y)


class RigSampleReviewer:
    """Review stable frame pairs before they enter the final rig solve."""

    def __init__(
        self,
        camera0: CameraCalibration,
        camera1: CameraCalibration,
        config: InteractiveRigConfig,
    ) -> None:
        self.camera0 = camera0
        self.camera1 = camera1
        self.config = config
        self._frame_shapes: Optional[Tuple[Tuple[int, ...], Tuple[int, ...]]] = None
        self._geometry0: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]] = None
        self._geometry1: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]] = None
        self._mask0: Optional[np.ndarray] = None
        self._mask1: Optional[np.ndarray] = None

    def _prepare_geometry(self, frame0: np.ndarray, frame1: np.ndarray) -> None:
        frame_shapes = (tuple(frame0.shape), tuple(frame1.shape))
        if self._frame_shapes == frame_shapes:
            return
        config = self.config
        self._geometry0 = _single_camera_equirectangular_geometry(
            self.camera0,
            frame0.shape,
            config.equirectangular_width,
            config.equirectangular_height,
        )
        camera1_mount = camera1_mount_rotation()
        self._geometry1 = _single_camera_equirectangular_geometry(
            self.camera1,
            frame1.shape,
            config.equirectangular_width,
            config.equirectangular_height,
            ray_rotation=camera1_mount,
        )
        self._mask0 = _feature_mask(
            self._geometry0[2],
            config.latitude_limit_deg,
            config.mask_erode_pixels,
        )
        self._mask1 = _feature_mask(
            self._geometry1[2],
            config.latitude_limit_deg,
            config.mask_erode_pixels,
        )
        self._frame_shapes = frame_shapes

    def _result(
        self,
        accepted: bool,
        reason: str,
        diagnostics: Mapping[str, Any],
        equi0: np.ndarray,
        equi1: np.ndarray,
        *,
        points0: Optional[np.ndarray] = None,
        points1: Optional[np.ndarray] = None,
        inliers: Optional[np.ndarray] = None,
        rotation: Optional[np.ndarray] = None,
    ) -> RigSampleReview:
        return RigSampleReview(
            accepted=accepted,
            reason=reason,
            diagnostics=dict(diagnostics),
            equi0=equi0,
            equi1=equi1,
            points0=(
                np.empty((0, 2), dtype=np.float64) if points0 is None else points0
            ),
            points1=(
                np.empty((0, 2), dtype=np.float64) if points1 is None else points1
            ),
            inliers=(np.empty((0,), dtype=bool) if inliers is None else inliers),
            rotation=rotation,
        )

    def review(self, frame0: np.ndarray, frame1: np.ndarray) -> RigSampleReview:
        """Remap, match, estimate one rotation, and apply every quality gate."""
        self._prepare_geometry(frame0, frame1)
        assert (
            self._geometry0 is not None
            and self._geometry1 is not None
            and self._mask0 is not None
            and self._mask1 is not None
        )
        equi0, _ = _remap_single_camera_equirectangular(frame0, self._geometry0)
        equi1, _ = _remap_single_camera_equirectangular(frame1, self._geometry1)
        try:
            points0, points1, match_info = _match_equirectangular_features(
                equi0,
                equi1,
                self._mask0,
                self._mask1,
                self.config,
            )
        except RuntimeError as exc:
            match_diagnostics = dict(getattr(exc, "diagnostics", {}))
            match_diagnostics["match_error"] = str(exc)
            return self._result(
                False,
                str(exc),
                match_diagnostics,
                equi0,
                equi1,
            )

        diagnostics: Dict[str, Any] = dict(match_info)
        minimum_keypoints = self.config.minimum_keypoints_per_camera
        if (
            match_info["keypoints0"] < minimum_keypoints
            or match_info["keypoints1"] < minimum_keypoints
        ):
            return self._result(
                False,
                "not enough SIFT keypoints: cam0={} cam1={} (minimum {})".format(
                    match_info["keypoints0"],
                    match_info["keypoints1"],
                    minimum_keypoints,
                ),
                diagnostics,
                equi0,
                equi1,
                points0=points0,
                points1=points1,
            )
        if match_info["matches"] < self.config.minimum_matches_per_sample:
            return self._result(
                False,
                "not enough mutual SIFT matches: {} (minimum {})".format(
                    match_info["matches"],
                    self.config.minimum_matches_per_sample,
                ),
                diagnostics,
                equi0,
                equi1,
                points0=points0,
                points1=points1,
            )

        rays0 = _equirectangular_points_to_rays(points0, equi0.shape[1], equi0.shape[0])
        rays1 = _equirectangular_points_to_rays(points1, equi1.shape[1], equi1.shape[0])
        try:
            rotation, inliers, angular_errors = calibrate_rig_rotation(
                rays0,
                rays1,
                ransac_threshold_deg=self.config.ransac_threshold_deg,
                ransac_iterations=self.config.sample_ransac_iterations,
            )
        except (RuntimeError, np.linalg.LinAlgError) as exc:
            diagnostics["rotation_error"] = str(exc)
            return self._result(
                False,
                str(exc),
                diagnostics,
                equi0,
                equi1,
                points0=points0,
                points1=points1,
            )
        reprojection_errors = _equirectangular_reprojection_errors(
            rotation,
            rays0,
            points1,
            equi0.shape[1],
            equi0.shape[0],
        )
        inlier_count = int(np.count_nonzero(inliers))
        inlier_ratio = float(np.mean(inliers))
        inlier_reprojection = reprojection_errors[inliers]
        inlier_angular = angular_errors[inliers]
        mean_angular = float(np.mean(inlier_angular)) if inlier_count else None
        maximum_angular = float(np.max(inlier_angular)) if inlier_count else None
        mean_reprojection = (
            float(np.mean(inlier_reprojection)) if inlier_count else None
        )
        median_reprojection = (
            float(np.median(inlier_reprojection)) if inlier_count else None
        )
        rmse_reprojection = (
            float(np.sqrt(np.mean(inlier_reprojection**2))) if inlier_count else None
        )
        maximum_reprojection = (
            float(np.max(inlier_reprojection)) if inlier_count else None
        )
        diagnostics.update(
            {
                "inlier_count": inlier_count,
                "inlier_ratio": inlier_ratio,
                "mean_inlier_angular_error_deg": mean_angular,
                "maximum_inlier_angular_error_deg": maximum_angular,
                "mean_inlier_reprojection_error_px": mean_reprojection,
                "median_inlier_reprojection_error_px": median_reprojection,
                "rmse_inlier_reprojection_error_px": rmse_reprojection,
                "maximum_inlier_reprojection_error_px": maximum_reprojection,
                "candidate_R_cam1_to_cam0": rotation.tolist(),
                "rotation_estimator": (
                    "reference four-ray spherical RANSAC + iterative Kabsch SVD"
                ),
            }
        )

        if inlier_count < self.config.minimum_sample_inliers:
            reason = "not enough RANSAC inliers: {} (minimum {})".format(
                inlier_count,
                self.config.minimum_sample_inliers,
            )
        elif inlier_ratio < self.config.minimum_sample_inlier_ratio:
            reason = "sample inlier ratio {:.1%} is below {:.1%}".format(
                inlier_ratio,
                self.config.minimum_sample_inlier_ratio,
            )
        elif (
            maximum_reprojection is not None
            and maximum_reprojection > self.config.maximum_sample_reprojection_error_px
        ):
            reason = (
                "maximum inlier reprojection error {:.2f}px exceeds {:.2f}px"
            ).format(
                maximum_reprojection,
                self.config.maximum_sample_reprojection_error_px,
            )
        else:
            reason = "stable frame pair passed SIFT and reprojection checks"
            return self._result(
                True,
                reason,
                diagnostics,
                equi0,
                equi1,
                points0=points0,
                points1=points1,
                inliers=inliers,
                rotation=rotation,
            )
        return self._result(
            False,
            reason,
            diagnostics,
            equi0,
            equi1,
            points0=points0,
            points1=points1,
            inliers=inliers,
            rotation=rotation,
        )


def update_calibration_intrinsics(
    path: PathLike,
    intrinsics: DualCameraIntrinsics,
    *,
    diagnostics: Optional[Mapping[str, Any]] = None,
) -> Path:
    """Create/update one calibration-result and invalidate any old rig solve."""
    output = Path(path)
    if output.exists():
        existing = load_calibration_document(output)
        merged_diagnostics = dict(existing["diagnostics"])
    else:
        merged_diagnostics = {}
    merged_diagnostics["intrinsics"] = dict(diagnostics or {})
    merged_diagnostics.pop("rig", None)
    document = calibration_document_from_intrinsics(intrinsics)
    document["diagnostics"] = merged_diagnostics
    return update_calibration_document(
        output,
        document,
    )


def load_calibration_intrinsics(path: PathLike) -> DualCameraIntrinsics:
    """Load K/D from the shared partial-or-complete calibration-result."""
    return calibration_intrinsics_from_document(load_calibration_document(path))


def _intrinsics_match(
    first: DualCameraIntrinsics,
    second: DualCameraIntrinsics,
) -> bool:
    return (
        first.camera0.width == second.camera0.width
        and first.camera0.height == second.camera0.height
        and np.isclose(
            first.camera0.fisheye_fov_deg,
            second.camera0.fisheye_fov_deg,
        )
        and first.camera1.width == second.camera1.width
        and first.camera1.height == second.camera1.height
        and np.isclose(
            first.camera1.fisheye_fov_deg,
            second.camera1.fisheye_fov_deg,
        )
        and np.allclose(first.camera0.K, second.camera0.K)
        and np.allclose(first.camera0.D, second.camera0.D)
        and np.allclose(first.camera1.K, second.camera1.K)
        and np.allclose(first.camera1.D, second.camera1.D)
    )


def update_calibration_profile(
    path: PathLike,
    calibration: CalibrationProfile,
    *,
    diagnostics: Optional[Mapping[str, Any]] = None,
) -> Path:
    """Atomically add/update rig rotation in the same calibration-result."""
    validate_calibration(calibration)
    output = Path(path)
    if not output.is_file():
        raise FileNotFoundError(str(output))
    existing = load_calibration_document(output)
    existing_intrinsics = calibration_intrinsics_from_document(existing)
    profile_intrinsics = DualCameraIntrinsics(
        calibration.camera0,
        calibration.camera1,
    )
    if not _intrinsics_match(existing_intrinsics, profile_intrinsics):
        raise MetadataError(
            "calibration-result intrinsics changed during rig calibration"
        )
    merged_diagnostics = dict(existing["diagnostics"])
    merged_diagnostics.update(dict(diagnostics or {}))
    document = calibration_result_from_profile(
        calibration,
        merged_diagnostics,
    )
    return update_calibration_document(output, document)


def solve_rig_samples(
    camera0: CameraCalibration,
    camera1: CameraCalibration,
    samples: Sequence[Tuple[np.ndarray, np.ndarray]],
    timing: Sequence[Mapping[str, float]],
    config: InteractiveRigConfig,
    *,
    matched_points: Optional[
        Sequence[Tuple[np.ndarray, np.ndarray, Mapping[str, Any]]]
    ] = None,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Solve relative rotation from already captured synchronized BGR pairs."""
    if not samples and not matched_points:
        raise ValueError("at least one captured rig sample is required")
    all_rays0: List[np.ndarray] = []
    all_rays1: List[np.ndarray] = []
    all_points1: List[np.ndarray] = []
    all_frame_ids: List[np.ndarray] = []
    per_sample: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    if matched_points is None:
        geometry0 = _single_camera_equirectangular_geometry(
            camera0,
            samples[0][0].shape,
            config.equirectangular_width,
            config.equirectangular_height,
        )
        camera1_mount = camera1_mount_rotation()
        geometry1 = _single_camera_equirectangular_geometry(
            camera1,
            samples[0][1].shape,
            config.equirectangular_width,
            config.equirectangular_height,
            ray_rotation=camera1_mount,
        )
        mask0 = _feature_mask(
            geometry0[2],
            config.latitude_limit_deg,
            config.mask_erode_pixels,
        )
        mask1 = _feature_mask(
            geometry1[2],
            config.latitude_limit_deg,
            config.mask_erode_pixels,
        )
        candidates = []
        for index, (frame0, frame1) in enumerate(samples):
            equi0, _ = _remap_single_camera_equirectangular(frame0, geometry0)
            equi1, _ = _remap_single_camera_equirectangular(frame1, geometry1)
            try:
                points0, points1, match_info = _match_equirectangular_features(
                    equi0, equi1, mask0, mask1, config
                )
            except RuntimeError as exc:
                skipped.append({"sample": index, "reason": str(exc)})
                continue
            candidates.append((index, points0, points1, match_info))
        final_match_source = "rematched captured frames"
    else:
        candidates = [
            (index, points0, points1, dict(match_info))
            for index, (points0, points1, match_info) in enumerate(matched_points)
        ]
        final_match_source = "accepted interactive sample matches"

    for index, points0, points1, match_info in candidates:
        rays0 = _equirectangular_points_to_rays(
            points0,
            config.equirectangular_width,
            config.equirectangular_height,
        )
        rays1 = _equirectangular_points_to_rays(
            points1,
            config.equirectangular_width,
            config.equirectangular_height,
        )
        all_rays0.append(rays0)
        all_rays1.append(rays1)
        all_points1.append(points1)
        all_frame_ids.append(np.full(len(rays0), index, dtype=np.int32))
        sample_timing = dict(timing[index]) if index < len(timing) else {}
        per_sample.append(
            {
                "sample": index,
                "keypoints0": match_info["keypoints0"],
                "keypoints1": match_info["keypoints1"],
                "matches": match_info["matches"],
                **sample_timing,
            }
        )
    if not all_rays0:
        raise RuntimeError("no rig sample produced reliable mutual SIFT matches")
    rays0_all = np.vstack(all_rays0)
    rays1_all = np.vstack(all_rays1)
    points1_all = np.vstack(all_points1)
    frame_ids_all = np.concatenate(all_frame_ids)
    rotation, inliers, errors = calibrate_rig_rotation(
        rays0_all,
        rays1_all,
        ransac_threshold_deg=config.ransac_threshold_deg,
        ransac_iterations=config.ransac_iterations,
    )
    inlier_count = int(np.count_nonzero(inliers))
    inlier_ratio = float(np.mean(inliers))
    if (
        inlier_count < config.minimum_inliers
        or inlier_ratio < config.minimum_inlier_ratio
    ):
        raise RuntimeError(
            "rig rotation confidence too low: {} inliers ({:.1f}%)".format(
                inlier_count, inlier_ratio * 100.0
            )
        )
    reprojection_errors = _equirectangular_reprojection_errors(
        rotation,
        rays0_all,
        points1_all,
        config.equirectangular_width,
        config.equirectangular_height,
    )
    inlier_angular_errors = errors[inliers]
    inlier_reprojection_errors = reprojection_errors[inliers]
    for report in per_sample:
        sample_mask = frame_ids_all == report["sample"]
        sample_match_count = int(np.count_nonzero(sample_mask))
        sample_inlier_count = int(np.count_nonzero(inliers & sample_mask))
        report["global_inliers"] = sample_inlier_count
        report["global_inlier_ratio"] = sample_inlier_count / max(
            1,
            sample_match_count,
        )
    diagnostics = {
        "definition": "ray_cam0 = R_cam1_to_cam0 @ ray_cam1",
        "feature_input": "two independently remapped equirectangular images",
        "feature_detector": "SIFT",
        "feature_matching": "mutual ratio-tested descriptors",
        "final_match_source": final_match_source,
        "feature_scale": config.feature_scale,
        "nfeatures": config.nfeatures,
        "sift_contrast_threshold": config.sift_contrast_threshold,
        "clahe_clip_limit": config.clahe_clip_limit,
        "clahe_tile_grid_size": list(config.clahe_tile_grid_size),
        "ratio_threshold": config.ratio_threshold,
        "mutual_matching": config.mutual_matching,
        "latitude_limit_deg": config.latitude_limit_deg,
        "mask_erode_pixels": config.mask_erode_pixels,
        "captured_samples": len(samples),
        "used_samples": len(per_sample),
        "raw_matches": int(len(errors)),
        "inlier_count": inlier_count,
        "inlier_ratio": inlier_ratio,
        "mean_inlier_error_deg": float(np.mean(inlier_angular_errors)),
        "median_inlier_error_deg": float(np.median(inlier_angular_errors)),
        "rmse_inlier_error_deg": float(
            np.sqrt(np.mean(inlier_angular_errors**2))
        ),
        "maximum_inlier_error_deg": float(np.max(inlier_angular_errors)),
        "mean_inlier_reprojection_error_px": float(
            np.mean(inlier_reprojection_errors)
        ),
        "median_inlier_reprojection_error_px": float(
            np.median(inlier_reprojection_errors)
        ),
        "rmse_inlier_reprojection_error_px": float(
            np.sqrt(np.mean(inlier_reprojection_errors**2))
        ),
        "maximum_inlier_reprojection_error_px": float(
            np.max(inlier_reprojection_errors)
        ),
        "R_cam1_to_cam0": rotation.tolist(),
        "determinant": float(np.linalg.det(rotation)),
        "rotation_estimator": (
            "reference four-ray spherical RANSAC + iterative Kabsch SVD"
        ),
        "ransac_threshold_deg": config.ransac_threshold_deg,
        "ransac_iterations": config.ransac_iterations,
        "svd_refinement_max_iterations": 8,
        "per_sample": per_sample,
        "skipped_samples": skipped,
    }
    return rotation, diagnostics


def save_calibration_profile(
    path: PathLike,
    calibration: CalibrationProfile,
    *,
    diagnostics: Optional[Mapping[str, Any]] = None,
    overwrite: bool = False,
) -> Path:
    """Atomically save the complete calibration-result JSON document."""
    validate_calibration(calibration)
    return save_calibration_result(
        path,
        calibration_result_from_profile(calibration, diagnostics),
        overwrite=overwrite,
    )


def load_calibration_profile(path: PathLike) -> CalibrationProfile:
    return calibration_profile_from_result(load_calibration_result(path))


__all__ = [
    "DEFAULT_INTRINSIC_GUIDE_STAGES",
    "InteractiveIntrinsicConfig",
    "InteractiveRigConfig",
    "IntrinsicGuideStage",
    "RigSampleReview",
    "RigSampleReviewer",
    "calibrate_intrinsics",
    "calibrate_intrinsics_camera0",
    "calibrate_intrinsics_camera1",
    "calibrate_rig_rotation",
    "fisheye_pixels_to_unit_rays",
    "load_calibration_intrinsics",
    "load_calibration_profile",
    "save_calibration_profile",
    "solve_rig_samples",
    "solve_rotation_svd",
    "update_calibration_intrinsics",
    "update_calibration_profile",
]
