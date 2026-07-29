"""Preview the same RPI360 recording in common application aspect ratios."""

from __future__ import annotations

import argparse
from pathlib import Path

from rpi360 import Player
from rpi360.adapters.opencv_viewer import run_viewer

SIZES = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (900, 900),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--aspect-ratio",
        choices=tuple(SIZES),
        default="16:9",
    )
    parser.add_argument("--fov", type=float, default=100.0)
    args = parser.parse_args()

    with Player.mp4(
        args.input,
        projection="perspective",
        size=SIZES[args.aspect_ratio],
        fov=args.fov,
    ) as player:
        run_viewer(
            player,
            window="RPI360 {}".format(args.aspect_ratio),
        )


if __name__ == "__main__":
    main()
