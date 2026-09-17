"""Show all stitching stages and projections in one comparison window."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
from rpi360 import Player, projection_grid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--timestamp", type=float, default=2.0)
    args = parser.parse_args()

    with Player.mp4(args.input, paced=False) as player:
        player.seek(args.timestamp)
        frame = player.next(timeout=None)
        if frame is None:
            raise RuntimeError("the requested timestamp contains no frame")
        image = projection_grid(frame)
        cv2.imshow("RPI360 projection gallery", image)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
