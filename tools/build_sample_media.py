"""Build the small public RPI360 samples from the three original camera pairs."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from rpi360.common.metadata import (
    calibration_profile_from_result,
    load_calibration_result,
    require_executable,
)
from rpi360.rpi.recording import mux_recording

SAMPLES = {
    "20260506_160728": "lake.r360.mp4",
    "20260506_161921": "steps.r360.mp4",
    "20260506_164938": "waterfront.r360.mp4",
}


def encode_track(source: Path, output: Path) -> None:
    selection = (
        "select=between(n\\,105\\,230),"
        "scale=1640:1232:flags=lanczos,"
        "setpts=N/(21*TB)"
    )
    subprocess.run(
        [
            require_executable("ffmpeg"),
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            selection,
            "-an",
            "-frames:v",
            "126",
            "-r",
            "21",
            "-fps_mode",
            "cfr",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-b:v",
            "2200k",
            "-maxrate",
            "2600k",
            "-bufsize",
            "4400k",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("calibration", type=Path)
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("assets/samples"),
    )
    args = parser.parse_args()

    result = load_calibration_result(args.calibration)
    profile = calibration_profile_from_result(result)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="rpi360-samples-"))
    try:
        for session, output_name in SAMPLES.items():
            tracks = []
            for camera in ("cam0", "cam1"):
                source = args.source_root / session / "{}.mp4".format(camera)
                if not source.is_file():
                    raise FileNotFoundError(str(source))
                track = temporary / "{}-{}.mp4".format(session, camera)
                encode_track(source, track)
                tracks.append(track)
            output = args.output_directory / output_name
            mux_recording(
                (tracks[0], tracks[1]),
                output,
                fps=21.0,
                calibration=profile,
                calibration_result=result,
                overwrite=True,
            )
            print(output)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    main()
