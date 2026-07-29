"""Public RPI360 API."""

from .common.frames import FrameBundle, PlayerFrame, View, ViewSnapshot
from .common.player import Player
from .common.types import (
    CalibrationProfile,
    CameraCalibration,
    CaptureError,
    DualCameraIntrinsics,
    ExternalToolError,
    FrameOutput,
    InvalidStateError,
    MetadataError,
    OperationCancelled,
    PlayerState,
    R360Error,
    UnsupportedOperationError,
)
from .effects import EFFECT_NAMES, EffectState, apply_effect, effect_state
from .rpi.calibration import (
    CalibrationEvent,
    InteractiveIntrinsicConfig,
    InteractiveRigConfig,
    IntrinsicCalibrationSession,
    RigVideoCaptureResult,
    RigVideoRecorder,
    load_calibration_intrinsics,
)
from .rpi.calibration.video import VideoRigCalibrationSession
from .rpi.calibration.workflow import RigCalibrationWorkflow
from .rpi.recording import RecordingHandle, RecordingStatus
from .visuals import projection_grid

__all__ = [
    "CalibrationEvent",
    "CalibrationProfile",
    "CameraCalibration",
    "CaptureError",
    "DualCameraIntrinsics",
    "ExternalToolError",
    "EFFECT_NAMES",
    "EffectState",
    "FrameOutput",
    "FrameBundle",
    "IntrinsicCalibrationSession",
    "InteractiveIntrinsicConfig",
    "InteractiveRigConfig",
    "InvalidStateError",
    "MetadataError",
    "OperationCancelled",
    "Player",
    "PlayerFrame",
    "PlayerState",
    "R360Error",
    "RecordingHandle",
    "RecordingStatus",
    "RigVideoCaptureResult",
    "RigVideoRecorder",
    "RigCalibrationWorkflow",
    "load_calibration_intrinsics",
    "projection_grid",
    "UnsupportedOperationError",
    "VideoRigCalibrationSession",
    "View",
    "ViewSnapshot",
    "apply_effect",
    "effect_state",
]
