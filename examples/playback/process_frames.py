"""Use every MP4 stage in a service-friendly pull loop."""

from __future__ import annotations

import argparse
from pathlib import Path

from rpi360 import FrameOutput, Player


def publish(_name: str, _bgr_image: object) -> None:
    """Replace this function with a queue, web handler, encoder, or model."""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    with Player.mp4(args.input, paced=False) as player:
        count = 0
        while args.limit is None or count < args.limit:
            frame = player.next(timeout=None)
            if frame is None:
                break
            for output in FrameOutput:
                publish(output.value, frame.output(output))
            count += 1


if __name__ == "__main__":
    main()
