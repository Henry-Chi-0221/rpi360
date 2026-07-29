"""Calibrate camera 0 and camera 1 intrinsics into a reusable JSON file."""

from __future__ import annotations

import argparse
from pathlib import Path

from rpi360 import InteractiveIntrinsicConfig, IntrinsicCalibrationSession
from rpi360.rpi.calibration.opencv import run_intrinsic_calibration_ui


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("calibration", type=Path)
    parser.add_argument("--camera0", type=int, default=0)
    parser.add_argument("--camera1", type=int, default=1)
    parser.add_argument(
        "--fisheye-fov",
        type=float,
        default=210.0,
        help="usable circular lens field of view in degrees",
    )
    parser.add_argument("--square-size", type=float, default=18.0)
    args = parser.parse_args()

    session = IntrinsicCalibrationSession(
        camera0=args.camera0,
        camera1=args.camera1,
        config=InteractiveIntrinsicConfig(
            fisheye_fov_deg=args.fisheye_fov,
            square_size=args.square_size,
        ),
    )
    output = run_intrinsic_calibration_ui(
        session,
        output=args.calibration,
    )
    if output is not None:
        print(output)


if __name__ == "__main__":
    main()
