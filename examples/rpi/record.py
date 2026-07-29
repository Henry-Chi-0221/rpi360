"""Record two RPi fisheye streams and the calibration result into one MP4."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from rpi360 import Player


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("calibration", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    with Player.live(args.calibration) as player:
        recording = player.start_recording(args.output, overwrite=args.overwrite)
        started = time.monotonic()
        try:
            while args.duration is None or time.monotonic() - started < args.duration:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        print(recording.stop())


if __name__ == "__main__":
    main()
