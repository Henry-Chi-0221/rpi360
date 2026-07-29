"""RPI360 calibration, live capture, recording, and MP4 playback CLI."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence, Tuple

from .adapters.opencv_viewer import DISPLAY_CHOICES, run_viewer, viewer_settings
from .common.player import Player
from .common.types import R360Error
from .playback.mp4 import RPI360Recording
from .rpi.calibration import (
    InteractiveIntrinsicConfig,
    InteractiveRigConfig,
    IntrinsicCalibrationSession,
    load_calibration_intrinsics,
)
from .rpi.calibration.opencv import run_intrinsic_calibration_ui
from .rpi.calibration.workflow import RigCalibrationWorkflow


def _size(value: str) -> Tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x", 1))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("size must look like WIDTHxHEIGHT") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("size values must be positive")
    return width, height


def _camera_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--camera0", type=int, default=0)
    parser.add_argument("--camera1", type=int, default=1)


def _viewer_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--display", choices=DISPLAY_CHOICES, default="stereographic")
    parser.add_argument("--size", type=_size, default=(1280, 720))
    parser.add_argument("--fov", type=float)
    parser.add_argument(
        "--quality", choices=("fast", "balanced", "high"), default="fast"
    )
    parser.add_argument("--panorama-size", type=_size, default=(2048, 1024))


def command_inspect(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            RPI360Recording.open(args.input).inspect(),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def command_play(args: argparse.Namespace) -> int:
    projection, display = viewer_settings(args.display)
    with Player.mp4(
        args.input,
        projection=projection,
        size=args.size,
        fov=args.fov,
        quality=args.quality,
        panorama_size=args.panorama_size,
        speed=args.speed,
        decode_size="native" if args.native_decode else "calibration",
    ) as player:
        run_viewer(player, display=display)
    return 0


def command_live(args: argparse.Namespace) -> int:
    projection, display = viewer_settings(args.display)
    with Player.live(
        args.calibration,
        camera_indices=(args.camera0, args.camera1),
        projection=projection,
        size=args.size,
        fov=args.fov,
        quality=args.quality,
        panorama_size=args.panorama_size,
        preview_size=args.preview_size,
        fps=args.fps,
    ) as player:
        run_viewer(player, window="RPI360 Live", display=display)
    return 0


def command_record(args: argparse.Namespace) -> int:
    with Player.live(
        args.calibration,
        camera_indices=(args.camera0, args.camera1),
        preview_size=args.preview_size,
        record_size=args.record_size,
        fps=args.fps,
    ) as player:
        handle = player.start_recording(args.output, overwrite=args.overwrite)
        started = time.monotonic()
        try:
            while args.duration is None or time.monotonic() - started < args.duration:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        print(handle.stop())
    return 0


def command_calibrate_cameras(args: argparse.Namespace) -> int:
    config = InteractiveIntrinsicConfig(
        width=args.capture_size[0],
        height=args.capture_size[1],
        fps=args.fps,
        fisheye_fov_deg=args.fisheye_fov,
        checkerboard=args.checkerboard,
        square_size=args.square_size,
        target_samples=args.target_samples,
        coverage_target=args.coverage_target,
    )
    output = run_intrinsic_calibration_ui(
        IntrinsicCalibrationSession(
            camera0=args.camera0,
            camera1=args.camera1,
            config=config,
        ),
        output=args.calibration,
    )
    if output is None:
        return 130
    print(output)
    return 0


def _rig_event(event: object) -> None:
    stage = getattr(event, "stage", "")
    status = getattr(event, "status", "")
    diagnostics = dict(getattr(event, "diagnostics", {}) or {})
    if stage == "video_samples":
        maximum = diagnostics.get("maximum_inlier_reprojection_error_px")
        maximum_text = "n/a" if maximum is None else "{:.2f}px".format(maximum)
        print(
            "[{status}] frame={frame} stable={stable} matches={matches} "
            "inliers={inliers} max={maximum}".format(
                status=status,
                frame=int(diagnostics["frame_index"]),
                stable=bool(diagnostics["stable"]),
                matches=int(diagnostics.get("matches", 0)),
                inliers=int(diagnostics.get("inlier_count", 0)),
                maximum=maximum_text,
            ),
            flush=True,
        )
    elif stage == "rig_solve":
        print("[{}] {}".format(status, getattr(event, "message", "")), flush=True)


def command_calibrate_rig(args: argparse.Namespace) -> int:
    intrinsics = load_calibration_intrinsics(args.calibration)
    equirectangular_size = args.equirectangular_size or (0, 0)
    config = InteractiveRigConfig(
        width=intrinsics.camera0.width,
        height=intrinsics.camera0.height,
        fps=args.fps,
        sample_count=args.samples,
        capture_seconds=args.capture_seconds,
        equirectangular_width=equirectangular_size[0],
        equirectangular_height=equirectangular_size[1],
        feature_scale={"reference": 1.0, "balanced": 0.75}[args.quality],
        ransac_threshold_deg=args.ransac_threshold,
        motion_threshold=args.motion_threshold,
        stable_frames=args.stable_frames,
        minimum_keypoints_per_camera=args.minimum_keypoints,
        minimum_matches_per_sample=args.minimum_matches,
        minimum_sample_inliers=args.minimum_inliers,
        minimum_sample_inlier_ratio=args.minimum_inlier_ratio,
        maximum_sample_reprojection_error_px=args.maximum_reprojection_error,
    )
    if args.resume and args.work_dir is None:
        raise ValueError("--resume requires the original --work-dir")
    work_directory = args.work_dir or (
        Path("rig-calibration-work") / datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    workflow = RigCalibrationWorkflow(
        args.calibration,
        work_directory=work_directory,
        camera_indices=(args.camera0, args.camera1),
        config=config,
        record_size=args.record_size,
        opencv_threads=args.opencv_threads,
    )
    if not args.resume:
        print(
            "[STAGE 1/2] recording {:.1f}s; cameras close before solving".format(
                args.capture_seconds
            ),
            flush=True,
        )
    else:
        print("[STAGE 1/2] reusing {}".format(work_directory), flush=True)
    print("[WORK DIR] {}".format(work_directory), flush=True)
    output = workflow.run(resume=args.resume, on_event=_rig_event)
    print("[RESULT] {}".format(output), flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rpi360",
        description="Calibrate, capture, and view dual-fisheye RPI360 media",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = commands.add_parser("inspect", help="inspect RPI360 MP4 metadata")
    inspect_parser.add_argument("input", type=Path)
    inspect_parser.set_defaults(handler=command_inspect)

    play = commands.add_parser("play", help="play an RPI360 MP4")
    play.add_argument("input", type=Path)
    _viewer_arguments(play)
    play.add_argument("--speed", type=float, default=1.0)
    play.add_argument("--native-decode", action="store_true")
    play.set_defaults(handler=command_play)

    live = commands.add_parser("live", help="view both Raspberry Pi cameras")
    live.add_argument("calibration", type=Path)
    _camera_arguments(live)
    _viewer_arguments(live)
    live.add_argument("--preview-size", type=_size)
    live.add_argument("--fps", type=float)
    live.set_defaults(handler=command_live)

    cameras = commands.add_parser(
        "calibrate-cameras",
        help="update both camera intrinsics in calibration-result.json",
    )
    cameras.add_argument("calibration", type=Path)
    _camera_arguments(cameras)
    cameras.add_argument("--capture-size", type=_size, default=(1640, 1232))
    cameras.add_argument("--fps", type=float, default=21.0)
    cameras.add_argument("--fisheye-fov", type=float, default=210.0)
    cameras.add_argument("--checkerboard", type=_size, default=(9, 6))
    cameras.add_argument("--square-size", type=float, default=18.0)
    cameras.add_argument("--target-samples", type=int, default=30)
    cameras.add_argument("--coverage-target", type=float, default=0.8)
    cameras.set_defaults(handler=command_calibrate_cameras)

    rig = commands.add_parser(
        "calibrate-rig",
        help="record, close cameras, then update rig rotation in the same JSON",
    )
    rig.add_argument("calibration", type=Path)
    _camera_arguments(rig)
    rig.add_argument("--work-dir", type=Path)
    rig.add_argument("--resume", action="store_true")
    rig.add_argument("--capture-seconds", type=float, default=30.0)
    rig.add_argument("--samples", type=int, default=20)
    rig.add_argument("--fps", type=float, default=21.0)
    rig.add_argument("--record-size", type=_size)
    rig.add_argument(
        "--quality",
        choices=("reference", "balanced"),
        default="reference",
    )
    rig.add_argument("--opencv-threads", type=int, default=2)
    rig.add_argument("--equirectangular-size", type=_size)
    rig.add_argument("--motion-threshold", type=float, default=3.0)
    rig.add_argument("--stable-frames", type=int, default=6)
    rig.add_argument("--minimum-keypoints", type=int, default=40)
    rig.add_argument("--minimum-matches", type=int, default=12)
    rig.add_argument("--minimum-inliers", type=int, default=8)
    rig.add_argument("--minimum-inlier-ratio", type=float, default=0.25)
    rig.add_argument("--ransac-threshold", type=float, default=0.4)
    rig.add_argument("--maximum-reprojection-error", type=float, default=8.0)
    rig.set_defaults(handler=command_calibrate_rig)

    record = commands.add_parser(
        "record",
        help="record two H.264 tracks and the active calibration into one MP4",
    )
    record.add_argument("calibration", type=Path)
    record.add_argument("output", type=Path)
    _camera_arguments(record)
    record.add_argument("--preview-size", type=_size)
    record.add_argument("--record-size", type=_size)
    record.add_argument("--fps", type=float)
    record.add_argument("--duration", type=float)
    record.add_argument("--overwrite", action="store_true")
    record.set_defaults(handler=command_record)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (R360Error, ValueError, OSError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    sys.exit(main())
