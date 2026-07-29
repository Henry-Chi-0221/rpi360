"""Rebuild README animations and the projection grid from public samples."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable, Iterator, Tuple

import cv2
import numpy as np
from PIL import Image

from rpi360 import Player, View, effect_state, projection_grid

FrameMaker = Callable[[object, float], Tuple[np.ndarray, str]]


def sampled_frames(input_path: Path, duration: float, fps: float) -> Iterator[tuple]:
    with Player.mp4(
        input_path,
        paced=False,
        size=(640, 360),
        panorama_size=(1024, 512),
        decode_size=(820, 616),
        quality="fast",
    ) as player:
        first_timestamp = None
        next_output = 0.0
        while next_output < duration:
            frame = player.next(timeout=None)
            if frame is None:
                break
            timestamp = float(frame.timestamp or 0.0)
            if first_timestamp is None:
                first_timestamp = timestamp
            elapsed = timestamp - first_timestamp
            if elapsed + 1e-9 < next_output:
                continue
            yield frame, min(1.0, elapsed / duration)
            next_output += 1.0 / fps


def labeled(image: np.ndarray, text: str, size: Tuple[int, int]) -> np.ndarray:
    result = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    cv2.rectangle(result, (0, 0), (size[0], 44), (0, 0, 0), -1)
    cv2.putText(
        result,
        text,
        (14, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return result


def write_webp(
    input_path: Path,
    output_path: Path,
    maker: FrameMaker,
    *,
    duration: float = 6.0,
    fps: float = 10.0,
    size: Tuple[int, int] = (640, 360),
) -> None:
    images = []
    for frame, progress in sampled_frames(input_path, duration, fps):
        image, label = maker(frame, progress)
        bgr = labeled(image, label, size)
        images.append(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
    if not images:
        raise RuntimeError("{} produced no showcase frames".format(input_path))
    images[0].save(
        output_path,
        save_all=True,
        append_images=images[1:],
        duration=round(1000.0 / fps),
        loop=0,
        format="WEBP",
        quality=72,
        method=4,
    )


def effect_maker(name: str, *, square: bool = False) -> FrameMaker:
    def make(frame: object, progress: float) -> Tuple[np.ndarray, str]:
        state = effect_state(name, progress)
        size = (480, 480) if square else (640, 360)
        view = View(state.projection, size=size, fov=state.fov)
        view.set_orientation(state.yaw, state.pitch, state.roll)
        return frame.bundle.render(view, panorama_size=(1024, 512)), name

    return make


def hero(frame: object, progress: float) -> Tuple[np.ndarray, str]:
    if progress < 0.25:
        return frame.equi_blended, "Blended equirectangular"
    if progress < 0.6:
        local = (progress - 0.25) / 0.35
        view = View("perspective", size=(640, 360), fov=100.0)
        view.set_orientation(yaw=120.0 * local)
        return frame.bundle.render(view, panorama_size=(1024, 512)), "Perspective"
    local = (progress - 0.6) / 0.4
    view = View("stereographic", size=(640, 360), fov=220.0)
    view.set_orientation(yaw=120.0 * local, pitch=-25.0)
    return frame.bundle.render(view, panorama_size=(1024, 512)), "Stereographic"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-directory",
        type=Path,
        default=Path("assets/samples"),
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("assets/showcase"),
    )
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)

    lake = args.input_directory / "lake.r360.mp4"
    steps = args.input_directory / "steps.r360.mp4"
    waterfront = args.input_directory / "waterfront.r360.mp4"
    write_webp(lake, args.output_directory / "hero.webp", hero)
    write_webp(
        steps,
        args.output_directory / "tiny-planet.webp",
        effect_maker("tiny-planet", square=True),
        size=(480, 480),
    )
    write_webp(
        waterfront,
        args.output_directory / "view-controls.webp",
        effect_maker("perspective-orbit"),
    )

    with Player.mp4(
        lake,
        paced=False,
        panorama_size=(1024, 512),
        decode_size=(820, 616),
        quality="fast",
    ) as player:
        frame = player.next(timeout=None)
        if frame is None:
            raise RuntimeError("lake sample contains no frame")
        grid = projection_grid(frame, tile_size=(320, 180))
        if not cv2.imwrite(str(args.output_directory / "projection-grid.png"), grid):
            raise RuntimeError("could not write projection grid")


if __name__ == "__main__":
    main()
