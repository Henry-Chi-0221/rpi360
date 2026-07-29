"""Record first, close both cameras, then update rig rotation in one JSON."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from rpi360 import (
    InteractiveRigConfig,
    RigCalibrationWorkflow,
    load_calibration_intrinsics,
)


def show_progress(event: object) -> None:
    diagnostics = dict(getattr(event, "diagnostics", {}) or {})
    if getattr(event, "stage", "") == "video_samples":
        print(
            "[{status}] frame={frame} matches={matches} inliers={inliers}".format(
                status=getattr(event, "status", ""),
                frame=int(diagnostics["frame_index"]),
                matches=int(diagnostics.get("matches", 0)),
                inliers=int(diagnostics.get("inlier_count", 0)),
            ),
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("calibration", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument(
        "--quality",
        choices=("reference", "balanced"),
        default="reference",
    )
    args = parser.parse_args()
    if args.resume and args.work_dir is None:
        parser.error("--resume requires the original --work-dir")
    work_directory = args.work_dir or (
        Path("rig-calibration-work") / datetime.now().strftime("%Y%m%d-%H%M%S")
    )

    intrinsics = load_calibration_intrinsics(args.calibration)
    config = InteractiveRigConfig(
        width=intrinsics.camera0.width,
        height=intrinsics.camera0.height,
        capture_seconds=args.duration,
        sample_count=args.samples,
        feature_scale=1.0 if args.quality == "reference" else 0.75,
    )
    workflow = RigCalibrationWorkflow(
        args.calibration,
        work_directory=work_directory,
        config=config,
    )
    print(workflow.run(resume=args.resume, on_event=show_progress))


if __name__ == "__main__":
    main()
