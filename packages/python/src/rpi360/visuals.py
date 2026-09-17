"""Small reusable visualizations built entirely from public frame data."""

from __future__ import annotations

from typing import Iterable, Tuple

import cv2
import numpy as np

from .common.frames import PlayerFrame, View


def _tile(
    image: np.ndarray,
    label: str,
    size: Tuple[int, int],
) -> np.ndarray:
    width, height = size
    resized = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    result = resized.copy()
    cv2.rectangle(result, (0, 0), (width, 38), (0, 0, 0), -1)
    cv2.putText(
        result,
        label,
        (12, 26),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return result


def projection_grid(
    frame: PlayerFrame,
    *,
    tile_size: Tuple[int, int] = (480, 270),
) -> np.ndarray:
    """Return a labeled 2x3 BGR comparison of stitching and projections."""
    render_size = tile_size
    rows: Iterable[Tuple[str, np.ndarray]] = (
        ("camera 0 equirectangular", frame.equi_1),
        ("camera 1 equirectangular", frame.equi_2),
        ("blended equirectangular", frame.equi_blended),
        (
            "oriented equirectangular",
            frame.bundle.render(View("equirectangular", size=render_size)),
        ),
        (
            "perspective",
            frame.bundle.render(View("perspective", size=render_size, fov=100.0)),
        ),
        (
            "stereographic",
            frame.bundle.render(
                View("stereographic", size=render_size, fov=220.0)
            ),
        ),
    )
    tiles = [_tile(image, label, tile_size) for label, image in rows]
    return np.vstack((np.hstack(tiles[:3]), np.hstack(tiles[3:])))


__all__ = ["projection_grid"]
