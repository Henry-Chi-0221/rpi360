"""The single OpenCV keyboard/window adapter for every Player source."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional, Union

import cv2
import numpy as np

from ..common.frames import PlayerFrame
from ..common.player import Player
from ..common.types import FrameOutput, PlayerState

DISPLAY_CHOICES = (
    "perspective",
    "stereographic",
    "equirectangular",
    "equi_blended",
    "equi_1",
    "equi_2",
    "camera0",
    "camera1",
)


@dataclass
class _ViewerState:
    display: FrameOutput


def viewer_settings(display: str) -> tuple[str, FrameOutput]:
    """Map one user-facing display name to projection and frame output."""
    value = str(display).lower()
    if value not in DISPLAY_CHOICES:
        raise ValueError(
            "display must be one of {}".format(", ".join(DISPLAY_CHOICES))
        )
    if value in {"perspective", "stereographic", "equirectangular"}:
        return value, FrameOutput.VIEW
    return "stereographic", FrameOutput(value)


def _overlay(
    image: np.ndarray,
    player: Player,
    *,
    display: FrameOutput,
    message: Optional[str],
) -> np.ndarray:
    output = image.copy()
    frame = player.current
    timestamp = 0.0 if frame is None or frame.timestamp is None else frame.timestamp
    if player.source_kind == "mp4":
        timing = "{:.2f}/{:.2f}s  {:g}x".format(
            timestamp, player.duration or 0.0, player.speed
        )
        controls = "Space pause | J/L seek | ,/. step | 0 restart | [/] speed"
    else:
        timing = "LIVE  source {:.2f} FPS".format(player.fps)
        controls = "Space pause (capture continues) | timeline controls unavailable"
    lines = [
        "{}  {}  {}".format(player.state.value.upper(), player.source_kind, timing),
        "{}  {}  FOV {:.0f}  frame {}".format(
            display.value,
            player.view.projection,
            player.view.fov,
            0 if frame is None else frame.frame_index,
        ),
        "WASD view | Z/X roll | +/- FOV | 1-3 projections | 4-8 stages",
        controls + " | Q quit",
    ]
    if message:
        lines.append(message)
    for index, text in enumerate(lines):
        origin = (16, 30 + index * 26)
        cv2.putText(
            output,
            text,
            origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 0),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            output,
            text,
            origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return output


def _handle_key(
    player: Player,
    key: int,
    *,
    viewer: _ViewerState,
    rotation_step: float,
    seek_step: float,
) -> Optional[str]:
    if key < 0:
        return None
    key &= 0xFF
    if key in (27, ord("q")):
        return "quit"
    if key == ord(" "):
        player.toggle_pause()
    elif key == ord("a"):
        if viewer.display != FrameOutput.VIEW:
            return "View controls apply to projections selected with keys 1-3."
        player.rotate(yaw=-rotation_step)
    elif key == ord("d"):
        if viewer.display != FrameOutput.VIEW:
            return "View controls apply to projections selected with keys 1-3."
        player.rotate(yaw=rotation_step)
    elif key == ord("w"):
        if viewer.display != FrameOutput.VIEW:
            return "View controls apply to projections selected with keys 1-3."
        player.rotate(pitch=rotation_step)
    elif key == ord("s"):
        if viewer.display != FrameOutput.VIEW:
            return "View controls apply to projections selected with keys 1-3."
        player.rotate(pitch=-rotation_step)
    elif key == ord("z"):
        if viewer.display != FrameOutput.VIEW:
            return "View controls apply to projections selected with keys 1-3."
        player.rotate(roll=-rotation_step)
    elif key == ord("x"):
        if viewer.display != FrameOutput.VIEW:
            return "View controls apply to projections selected with keys 1-3."
        player.rotate(roll=rotation_step)
    elif key == ord("r"):
        player.reset_view()
    elif key == ord("1"):
        viewer.display = FrameOutput.VIEW
        player.configure("perspective", fov=90.0)
    elif key == ord("2"):
        viewer.display = FrameOutput.VIEW
        player.configure("stereographic", fov=150.0)
    elif key == ord("3"):
        viewer.display = FrameOutput.VIEW
        player.configure("equirectangular", fov=90.0)
    elif key == ord("4"):
        viewer.display = FrameOutput.EQUI_BLENDED
    elif key == ord("5"):
        viewer.display = FrameOutput.EQUI_1
    elif key == ord("6"):
        viewer.display = FrameOutput.EQUI_2
    elif key == ord("7"):
        viewer.display = FrameOutput.CAMERA0
    elif key == ord("8"):
        viewer.display = FrameOutput.CAMERA1
    elif key in (ord("-"), ord("_")):
        if viewer.display != FrameOutput.VIEW:
            return "FOV applies to projections selected with keys 1-3."
        player.configure(fov=max(10.0, player.view.fov - 5.0))
    elif key in (ord("+"), ord("=")):
        if viewer.display != FrameOutput.VIEW:
            return "FOV applies to projections selected with keys 1-3."
        maximum = 350.0 if player.view.projection == "stereographic" else 175.0
        player.configure(fov=min(maximum, player.view.fov + 5.0))
    elif key in (ord("j"), ord("l"), ord(","), ord("."), ord("0")):
        if not player.supports_timeline:
            return "This live source has no seek/step/restart timeline."
        if key == ord("j"):
            player.seek_by(-seek_step)
        elif key == ord("l"):
            player.seek_by(seek_step)
        elif key == ord(","):
            player.step(-1)
        elif key == ord("."):
            player.step(1)
        else:
            player.restart()
    elif key in (ord("["), ord("]")):
        if not player.supports_timeline:
            return "Playback speed is unavailable for a live source."
        factor = 0.8 if key == ord("[") else 1.25
        player.speed = min(8.0, max(0.125, player.speed * factor))
    return None


def run_viewer(
    player: Player,
    *,
    window: str = "RPI360 Player",
    display: Union[str, FrameOutput] = FrameOutput.VIEW,
    rotation_step: float = 3.0,
    seek_step: float = 5.0,
    overlay: bool = True,
    on_frame: Optional[Callable[[Player, PlayerFrame], None]] = None,
) -> None:
    """Block until Q/Escape/window-close while driving only public Player calls."""
    viewer = _ViewerState(FrameOutput(display))
    cv2.namedWindow(window, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    width, height = player.view.size
    loading = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.putText(
        loading,
        "Loading RPI360 source...",
        (max(16, width // 20), max(40, height // 2)),
        cv2.FONT_HERSHEY_SIMPLEX,
        max(0.6, min(width, height) / 900.0),
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.imshow(window, loading)
    cv2.waitKey(1)
    if player.state in {PlayerState.NEW, PlayerState.STOPPED}:
        player.start()
    message: Optional[str] = None
    message_until = 0.0
    try:
        while True:
            frame = player.next(timeout=0.03)
            if frame is not None and on_frame is not None:
                on_frame(player, frame)
                frame = player.next(timeout=0.0) or frame
            shown = frame or player.current
            if shown is not None:
                active_message = message if time.monotonic() < message_until else None
                selected = shown.output(viewer.display)
                image = (
                    _overlay(
                        selected,
                        player,
                        display=viewer.display,
                        message=active_message,
                    )
                    if overlay
                    else selected
                )
                cv2.imshow(window, image)
            key = cv2.waitKeyEx(1)
            result = _handle_key(
                player,
                key,
                viewer=viewer,
                rotation_step=rotation_step,
                seek_step=seek_step,
            )
            if result == "quit":
                break
            if result:
                message = result
                message_until = time.monotonic() + 2.0
            # Cocoa returns -1 because WND_PROP_VISIBLE is unsupported.
            # Qt/GTK return exactly 0 only after a supported window closes.
            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) == 0:
                break
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyWindow(window)


__all__ = ["DISPLAY_CHOICES", "run_viewer", "viewer_settings"]
