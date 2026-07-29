"""OpenCV UI adapters for the two headless calibration stages."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2

from ...common.types import PathLike, PipelineState
from .session import IntrinsicCalibrationSession


def _fitted_window_size(
    image_width: int,
    image_height: int,
    *,
    maximum_width: int = 1600,
    maximum_height: int = 900,
) -> tuple[int, int]:
    """Fit an image on screen without changing its aspect ratio."""
    if image_width <= 0 or image_height <= 0:
        raise ValueError("image dimensions must be positive")
    scale = min(
        1.0,
        maximum_width / float(image_width),
        maximum_height / float(image_height),
    )
    return (
        max(1, round(image_width * scale)),
        max(1, round(image_height * scale)),
    )


def _status_overlay(image, status: str, message: str):
    preview = image.copy()
    text = "{} | {}".format(status, message)
    cv2.putText(
        preview,
        text,
        (18, 32),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 0, 0),
        4,
        cv2.LINE_AA,
    )
    cv2.putText(
        preview,
        text,
        (18, 32),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 210, 40),
        2,
        cv2.LINE_AA,
    )
    return preview


def _run_session_ui(
    session: IntrinsicCalibrationSession,
    *,
    window: str,
    output: Optional[PathLike],
) -> Optional[Path]:
    cv2.namedWindow(window, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    paused = False
    displayed_shape: Optional[tuple[int, int]] = None
    last_preview = None
    displayed_status: Optional[str] = None
    try:
        if session.state != PipelineState.RUNNING:
            session.start()
        while session.state == PipelineState.RUNNING:
            wait_ms = 30 if paused else 1
            if not paused:
                event = session.step()
                preview = None if event is None else event.preview
                if preview is not None:
                    last_preview = preview
                    displayed_status = event.status
                elif (
                    event is not None
                    and last_preview is not None
                    and event.status != displayed_status
                ):
                    preview = _status_overlay(
                        last_preview,
                        event.status,
                        event.message,
                    )
                    displayed_status = event.status
                if preview is not None:
                    cv2.imshow(window, preview)
                    preview_shape = preview.shape[:2]
                    if preview_shape != displayed_shape:
                        height, width = preview_shape
                        cv2.resizeWindow(
                            window,
                            *_fitted_window_size(width, height),
                        )
                        displayed_shape = preview_shape
            key = cv2.waitKey(wait_ms) & 0xFF
            if key in (27, ord("q")):
                session.cancel()
                return None
            if key == ord(" "):
                paused = not paused
        if output is None:
            return None
        return session.save(output)
    finally:
        session.stop()
        cv2.destroyWindow(window)


def run_intrinsic_calibration_ui(
    session: IntrinsicCalibrationSession,
    *,
    output: Optional[PathLike] = None,
) -> Optional[Path]:
    """Interactively produce the reusable two-camera intrinsics JSON."""
    return _run_session_ui(
        session,
        window="RPI360 camera intrinsics",
        output=output,
    )


__all__ = ["run_intrinsic_calibration_ui"]
