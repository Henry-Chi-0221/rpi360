"""View two Raspberry Pi cameras with the same controls as MP4 playback."""

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
    parser.add_argument("calibration", type=Path)
    parser.add_argument("--display", choices=DISPLAY_CHOICES, default="stereographic")
    parser.add_argument("--camera0", type=int, default=0)
    parser.add_argument("--camera1", type=int, default=1)
    args = parser.parse_args()
    projection, output = viewer_settings(args.display)

    with Player.live(
        args.calibration,
        camera_indices=(args.camera0, args.camera1),
        projection=projection,
    ) as player:
        run_viewer(player, window="RPI360 Live", display=output)


if __name__ == "__main__":
    main()
