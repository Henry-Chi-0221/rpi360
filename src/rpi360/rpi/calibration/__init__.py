"""Calibration API."""

from .core import (
    DEFAULT_INTRINSIC_GUIDE_STAGES,
    InteractiveIntrinsicConfig,
    InteractiveRigConfig,
    IntrinsicGuideStage,
    RigSampleReview,
    RigSampleReviewer,
    calibrate_intrinsics,
    calibrate_intrinsics_camera0,
    calibrate_intrinsics_camera1,
    calibrate_rig_rotation,
    fisheye_pixels_to_unit_rays,
    load_calibration_intrinsics,
    load_calibration_profile,
    save_calibration_profile,
    solve_rig_samples,
    solve_rotation_svd,
    update_calibration_intrinsics,
    update_calibration_profile,
)
from .recording import RigVideoCaptureResult, RigVideoRecorder
from .session import (
    CalibrationEvent,
    IntrinsicCalibrationSession,
)

__all__ = [
    "CalibrationEvent",
    "DEFAULT_INTRINSIC_GUIDE_STAGES",
    "IntrinsicCalibrationSession",
    "InteractiveIntrinsicConfig",
    "InteractiveRigConfig",
    "IntrinsicGuideStage",
    "RigSampleReview",
    "RigSampleReviewer",
    "RigVideoCaptureResult",
    "RigVideoRecorder",
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
