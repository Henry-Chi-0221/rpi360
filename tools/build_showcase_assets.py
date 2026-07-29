"""Rebuild the README visuals and Full HD showcase clips from public samples."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Tuple

import cv2
import numpy as np
from PIL import Image

from rpi360 import Player, View, effect_state, projection_grid
from rpi360.common.metadata import require_executable

FULL_HD = (1920, 1080)
PREVIEW_SIZE = (960, 540)
PANORAMA_SIZE = (4096, 2048)
SHOWCASE_DURATION = 6.0
SHOWCASE_FPS = 6.0

FrameMaker = Callable[[object, float], Tuple[np.ndarray, str]]


@dataclass(frozen=True)
class Animation:
    name: str
    maker: FrameMaker


class Mp4Writer:
    """Small atomic raw-BGR-to-H.264 writer used only by this maintenance tool."""

    def __init__(
        self,
        output: Path,
        *,
        size: Tuple[int, int] = FULL_HD,
        fps: float = SHOWCASE_FPS,
    ) -> None:
        self.output = output
        self.size = size
        self.fps = fps
        self.process: subprocess.Popen = None  # type: ignore[assignment]
        self.temporary: Path = None  # type: ignore[assignment]
        self.closed = False

    def start(self) -> "Mp4Writer":
        self.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=".{}-".format(self.output.stem),
            suffix=".mp4",
            dir=str(self.output.parent),
            delete=False,
        ) as handle:
            self.temporary = Path(handle.name)
        width, height = self.size
        self.process = subprocess.Popen(
            [
                require_executable("ffmpeg"),
                "-v",
                "error",
                "-y",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "bgr24",
                "-s:v",
                "{}x{}".format(width, height),
                "-r",
                "{:.9g}".format(self.fps),
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(self.temporary),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        return self

    def write(self, frame: np.ndarray) -> None:
        if frame.shape[:2] != (self.size[1], self.size[0]):
            raise ValueError(
                "expected {}x{} showcase frame".format(*self.size)
            )
        if self.process.stdin is None:
            raise RuntimeError("showcase encoder is not running")
        self.process.stdin.write(np.ascontiguousarray(frame).tobytes())

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.process.stdin is not None:
            self.process.stdin.close()
        stderr = b""
        if self.process.stderr is not None:
            stderr = self.process.stderr.read()
        return_code = self.process.wait()
        if return_code != 0:
            self.temporary.unlink(missing_ok=True)
            raise RuntimeError(
                "ffmpeg could not build {}: {}".format(
                    self.output,
                    stderr.decode("utf-8", errors="replace").strip(),
                )
            )
        os.replace(str(self.temporary), str(self.output))

    def abort(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait()
        self.temporary.unlink(missing_ok=True)


def sampled_frames(
    input_path: Path,
    *,
    duration: float = SHOWCASE_DURATION,
    fps: float = SHOWCASE_FPS,
) -> Iterator[Tuple[object, float]]:
    frame_count = max(2, int(round(duration * fps)))
    with Player.mp4(
        input_path,
        paced=False,
        size=FULL_HD,
        panorama_size=PANORAMA_SIZE,
        decode_size="native",
        quality="fast",
    ) as player:
        first_timestamp = None
        sample_index = 0
        while sample_index < frame_count:
            frame = player.next(timeout=None)
            if frame is None:
                break
            timestamp = float(frame.timestamp or 0.0)
            if first_timestamp is None:
                first_timestamp = timestamp
            target = sample_index / fps
            if timestamp - first_timestamp + 1e-9 < target:
                continue
            yield frame, sample_index / (frame_count - 1)
            sample_index += 1


def labeled(
    image: np.ndarray,
    text: str,
    size: Tuple[int, int] = FULL_HD,
) -> np.ndarray:
    result = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    header_height = max(54, round(size[1] * 0.07))
    cv2.rectangle(result, (0, 0), (size[0], header_height), (0, 0, 0), -1)
    cv2.putText(
        result,
        text,
        (round(size[0] * 0.018), round(header_height * 0.7)),
        cv2.FONT_HERSHEY_SIMPLEX,
        max(0.8, size[0] / 1500.0),
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return result


def write_preview(output: Path, frames: List[Image.Image]) -> None:
    if not frames:
        raise RuntimeError("{} produced no preview frames".format(output))
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=round(1000.0 / SHOWCASE_FPS),
        loop=0,
        format="WEBP",
        quality=68,
        method=4,
    )


def write_animation_group(
    input_path: Path,
    output_directory: Path,
    animations: Tuple[Animation, ...],
) -> None:
    writers: Dict[str, Mp4Writer] = {}
    previews: Dict[str, List[Image.Image]] = {
        animation.name: [] for animation in animations
    }
    try:
        for animation in animations:
            writers[animation.name] = Mp4Writer(
                output_directory / "{}.mp4".format(animation.name)
            ).start()
        for frame, progress in sampled_frames(input_path):
            for animation in animations:
                image, label = animation.maker(frame, progress)
                output_frame = labeled(image, label)
                writers[animation.name].write(output_frame)
                preview = cv2.resize(
                    output_frame,
                    PREVIEW_SIZE,
                    interpolation=cv2.INTER_AREA,
                )
                previews[animation.name].append(
                    Image.fromarray(cv2.cvtColor(preview, cv2.COLOR_BGR2RGB))
                )
        for writer in writers.values():
            writer.close()
    except BaseException:
        for writer in writers.values():
            writer.abort()
        raise
    for animation in animations:
        write_preview(
            output_directory / "{}.webp".format(animation.name),
            previews[animation.name],
        )


def effect_maker(name: str) -> FrameMaker:
    def make(frame: object, progress: float) -> Tuple[np.ndarray, str]:
        state = effect_state(name, progress)
        view = View(state.projection, size=FULL_HD, fov=state.fov)
        view.set_orientation(state.yaw, state.pitch, state.roll)
        return frame.bundle.render(view, panorama_size=PANORAMA_SIZE), name

    return make


def hero(frame: object, progress: float) -> Tuple[np.ndarray, str]:
    if progress < 0.25:
        return frame.equi_blended, "Blended equirectangular"
    if progress < 0.6:
        local = (progress - 0.25) / 0.35
        view = View("perspective", size=FULL_HD, fov=100.0)
        view.set_orientation(yaw=120.0 * local)
        return (
            frame.bundle.render(view, panorama_size=PANORAMA_SIZE),
            "Perspective",
        )
    local = (progress - 0.6) / 0.4
    view = View("stereographic", size=FULL_HD, fov=220.0)
    view.set_orientation(yaw=120.0 * local, pitch=-25.0)
    return (
        frame.bundle.render(view, panorama_size=PANORAMA_SIZE),
        "Stereographic",
    )


def _place_panel(
    canvas: np.ndarray,
    image: np.ndarray,
    *,
    origin: Tuple[int, int],
    label: str,
) -> None:
    x, y = origin
    height, width = image.shape[:2]
    canvas[y : y + height, x : x + width] = image
    cv2.rectangle(canvas, (x, y - 52), (x + width, y), (0, 0, 0), -1)
    cv2.putText(
        canvas,
        label,
        (x + 12, y - 16),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def aspect_ratios(frame: object, progress: float) -> Tuple[np.ndarray, str]:
    canvas = np.full((FULL_HD[1], FULL_HD[0], 3), 22, dtype=np.uint8)
    yaw = 220.0 * progress
    specifications = (
        ("16:9  1920x1080", (1920, 1080), (820, 461), (55, 290)),
        ("9:16  1080x1920", (1080, 1920), (300, 533), (890, 254)),
        ("1:1  1440x1440", (1440, 1440), (533, 533), (1250, 254)),
    )
    for label, render_size, panel_size, origin in specifications:
        view = View("perspective", size=render_size, fov=100.0)
        view.set_orientation(yaw=yaw, pitch=-8.0)
        image = frame.bundle.render(view, panorama_size=PANORAMA_SIZE)
        panel = cv2.resize(image, panel_size, interpolation=cv2.INTER_AREA)
        _place_panel(canvas, panel, origin=origin, label=label)
    cv2.putText(
        canvas,
        "One stitched frame, multiple output aspect ratios",
        (55, 130),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.35,
        (255, 255, 255),
        3,
        cv2.LINE_AA,
    )
    return canvas, "Aspect-ratio independent views"


def write_projection_grid(input_path: Path, output_path: Path) -> None:
    with Player.mp4(
        input_path,
        paced=False,
        panorama_size=PANORAMA_SIZE,
        decode_size="native",
        quality="fast",
    ) as player:
        frame = player.next(timeout=None)
        if frame is None:
            raise RuntimeError("{} contains no frame".format(input_path))
        grid = projection_grid(frame, tile_size=(640, 360))
    canvas = np.full((1080, 1920, 3), 22, dtype=np.uint8)
    canvas[240:960] = grid
    cv2.putText(
        canvas,
        "Inspectable stages and output projections",
        (55, 135),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.45,
        (255, 255, 255),
        3,
        cv2.LINE_AA,
    )
    if not cv2.imwrite(str(output_path), canvas):
        raise RuntimeError("could not write projection grid")


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

    write_animation_group(
        lake,
        args.output_directory,
        (
            Animation("hero", hero),
            Animation("aspect-ratios", aspect_ratios),
        ),
    )
    write_animation_group(
        steps,
        args.output_directory,
        (
            Animation("tiny-planet", effect_maker("tiny-planet")),
            Animation("rabbit-hole", effect_maker("rabbit-hole")),
        ),
    )
    write_animation_group(
        waterfront,
        args.output_directory,
        (
            Animation(
                "perspective-orbit",
                effect_maker("perspective-orbit"),
            ),
            Animation("barrel-roll", effect_maker("barrel-roll")),
        ),
    )
    write_projection_grid(
        lake,
        args.output_directory / "projection-grid.png",
    )


if __name__ == "__main__":
    main()
