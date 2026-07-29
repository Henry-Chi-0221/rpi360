from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

from rpi360 import CalibrationProfile, CameraCalibration
from rpi360.common.metadata import (
    calibration_result_from_profile,
    calibration_to_metadata,
    probe_media,
    stream_descriptor,
    write_r360_metadata,
    write_recording_metadata,
)


def sample_calibration(width: int = 64, height: int = 64) -> CalibrationProfile:
    # With D=0, radius = f*theta. This maps a 180-degree hemisphere to a
    # circle whose radius is half the image width.
    focal = min(width, height) / np.pi
    K = np.array(
        [
            [focal, 0.0, width / 2.0],
            [0.0, focal, height / 2.0],
            [0.0, 0.0, 1.0],
        ]
    )
    camera = CameraCalibration(width, height, K, np.zeros(4))
    back_to_back = np.diag([-1.0, 1.0, -1.0])
    return CalibrationProfile(camera, camera, back_to_back)


def make_dual_track_recording(
    path: Path,
    *,
    reverse_camera_mapping: bool = False,
    embed_full_result: bool = True,
) -> CalibrationProfile:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg and ffprobe are required")
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=64x64:r=5:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:r=5:d=1",
            "-map",
            "0:v",
            "-map",
            "1:v",
            "-c:v",
            "mpeg4",
            "-streamid",
            "0:1",
            "-streamid",
            "1:2",
            str(path),
        ],
        check=True,
    )
    streams = [
        stream_descriptor(stream)
        for stream in probe_media(path)["streams"]
        if stream["codec_type"] == "video"
    ]
    camera0_stream, camera1_stream = (
        (streams[1], streams[0]) if reverse_camera_mapping else streams
    )
    calibration = sample_calibration()
    metadata = calibration_to_metadata(
        calibration,
        camera0_track_id=camera0_stream["track_id"],
        camera1_track_id=camera1_stream["track_id"],
        camera0_stream=camera0_stream,
        camera1_stream=camera1_stream,
    )
    if embed_full_result:
        write_recording_metadata(
            path, metadata, calibration_result_from_profile(calibration)
        )
    else:
        write_r360_metadata(path, metadata)
    return calibration
