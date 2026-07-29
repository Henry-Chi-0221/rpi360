"""Play an RPI360 MP4 and inspect every projection or processing stage."""

from __future__ import annotations

import argparse
from pathlib import Path

from rpi360 import Player
from rpi360.adapters.opencv_viewer import (
    DISPLAY_CHOICES,
    run_viewer,
    viewer_settings,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--display", choices=DISPLAY_CHOICES, default="stereographic")
    parser.add_argument("--size", nargs=2, type=int, default=(1280, 720))
    parser.add_argument("--fov", type=float)
    parser.add_argument(
        "--quality", choices=("fast", "balanced", "high"), default="fast"
    )
    args = parser.parse_args()
    projection, output = viewer_settings(args.display)

    with Player.mp4(
        args.input,
        projection=projection,
        size=tuple(args.size),
        fov=args.fov,
        quality=args.quality,
    ) as player:
        run_viewer(player, display=output)


if __name__ == "__main__":
    main()
