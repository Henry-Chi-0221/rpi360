"""Public transition API, loaded lazily; camera/client/core imports need no GUI."""

import importlib

__version__ = "2.0.0a1"
_EXPORTS = {
    "FrameBundle": (".common.frames", "FrameBundle"),
    "PlayerFrame": (".common.frames", "PlayerFrame"),
    "View": (".common.frames", "View"),
    "ViewSnapshot": (".common.frames", "ViewSnapshot"),
    "Player": (".common.player", "Player"),
    "CalibrationError": (".common.types", "CalibrationError"),
    "CalibrationProfile": (".common.types", "CalibrationProfile"),
    "CameraCalibration": (".common.types", "CameraCalibration"),
    "CaptureError": (".common.types", "CaptureError"),
    "DualCameraIntrinsics": (".common.types", "DualCameraIntrinsics"),
    "ExternalToolError": (".common.types", "ExternalToolError"),
    "FrameOutput": (".common.types", "FrameOutput"),
    "InvalidStateError": (".common.types", "InvalidStateError"),
    "MetadataError": (".common.types", "MetadataError"),
    "OperationCancelled": (".common.types", "OperationCancelled"),
    "PlayerState": (".common.types", "PlayerState"),
    "R360Error": (".common.types", "R360Error"),
    "UnsupportedOperationError": (".common.types", "UnsupportedOperationError"),
    "EFFECT_NAMES": (".effects", "EFFECT_NAMES"),
    "EffectState": (".effects", "EffectState"),
    "apply_effect": (".effects", "apply_effect"),
    "effect_state": (".effects", "effect_state"),
    "CalibrationEvent": (".rpi.calibration", "CalibrationEvent"),
    "InteractiveIntrinsicConfig": (".rpi.calibration", "InteractiveIntrinsicConfig"),
    "InteractiveRigConfig": (".rpi.calibration", "InteractiveRigConfig"),
    "IntrinsicCalibrationSession": (".rpi.calibration", "IntrinsicCalibrationSession"),
    "RigVideoCaptureResult": (".rpi.calibration", "RigVideoCaptureResult"),
    "RigVideoRecorder": (".rpi.calibration", "RigVideoRecorder"),
    "load_calibration_intrinsics": (".rpi.calibration", "load_calibration_intrinsics"),
    "VideoRigCalibrationSession": (
        ".rpi.calibration.video",
        "VideoRigCalibrationSession",
    ),
    "RigCalibrationWorkflow": (".rpi.calibration.workflow", "RigCalibrationWorkflow"),
    "RecordingHandle": (".rpi.recording", "RecordingHandle"),
    "RecordingStatus": (".rpi.recording", "RecordingStatus"),
    "projection_grid": (".visuals", "projection_grid"),
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    value = getattr(importlib.import_module(module, __name__), attribute)
    globals()[name] = value
    return value
