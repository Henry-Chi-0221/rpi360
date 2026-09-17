"""Preview deterministic tiny-planet, inverted-tiny-planet, orbit, and roll effects."""

from __future__ import annotations

import argparse
from pathlib import Path

from rpi360 import EFFECT_NAMES, Player, apply_effect
from rpi360.adapters.opencv_viewer import run_viewer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--effect", choices=EFFECT_NAMES, default="tiny-planet")
    parser.add_argument("--duration", type=float, default=6.0)
    args = parser.parse_args()
    if args.duration <= 0:
        parser.error("--duration must be positive")

    start_timestamp = None

    def update(player: Player, frame: object) -> None:
        nonlocal start_timestamp
        timestamp = float(getattr(frame, "timestamp", 0.0) or 0.0)
        if start_timestamp is None:
            start_timestamp = timestamp
        progress = ((timestamp - start_timestamp) / args.duration) % 1.0
        apply_effect(player, args.effect, progress)

    with Player.mp4(args.input, projection="stereographic") as player:
        run_viewer(player, on_frame=update)


if __name__ == "__main__":
    main()
