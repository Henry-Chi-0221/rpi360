"""Immutable frames, lazy stitch caches, and mutable view control."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Union

import numpy as np

from .rendering import (
    EquirectangularStages,
    render_equirectangular,
    stitch_equirectangular_stages,
)
from .types import (
    CalibrationProfile,
    FrameOutput,
    OrientationState,
    ViewConfig,
    rotation_matrix_from_euler,
)


@dataclass(frozen=True)
class ViewSnapshot:
    """Immutable render configuration captured atomically from a View."""

    config: ViewConfig
    rotation_matrix: np.ndarray


class View:
    """Thread-safe mutable projection and orientation controller."""

    def __init__(
        self,
        projection: str = "perspective",
        *,
        size: Tuple[int, int] = (1920, 1080),
        fov: Optional[float] = None,
        quality: str = "balanced",
        pixel_format: str = "bgr24",
    ) -> None:
        self._lock = threading.RLock()
        self._orientation = OrientationState.identity()
        self._config = self._make_config(projection, size, fov, quality, pixel_format)
        self._revision = 0

    @staticmethod
    def _default_fov(projection: str) -> float:
        return 150.0 if str(projection).lower() == "stereographic" else 90.0

    @classmethod
    def _make_config(
        cls,
        projection: str,
        size: Tuple[int, int],
        fov: Optional[float],
        quality: str,
        pixel_format: str,
    ) -> ViewConfig:
        return ViewConfig(
            projection=projection,
            width=int(size[0]),
            height=int(size[1]),
            horizontal_fov_deg=(
                cls._default_fov(projection) if fov is None else float(fov)
            ),
            quality=quality,
            pixel_format=pixel_format,
        )

    @property
    def projection(self) -> str:
        return self.snapshot().config.projection

    @property
    def size(self) -> Tuple[int, int]:
        config = self.snapshot().config
        return config.width, config.height

    @property
    def fov(self) -> float:
        return self.snapshot().config.horizontal_fov_deg

    @property
    def quality(self) -> str:
        return self.snapshot().config.quality

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def configure(
        self,
        projection: Optional[str] = None,
        *,
        size: Optional[Tuple[int, int]] = None,
        fov: Optional[float] = None,
        quality: Optional[str] = None,
        pixel_format: Optional[str] = None,
    ) -> "View":
        with self._lock:
            old = self._config
            new_projection = projection or old.projection
            new_size = size or (old.width, old.height)
            if fov is None:
                new_fov = (
                    self._default_fov(new_projection)
                    if projection is not None and new_projection != old.projection
                    else old.horizontal_fov_deg
                )
            else:
                new_fov = float(fov)
            new_config = self._make_config(
                new_projection,
                new_size,
                new_fov,
                quality or old.quality,
                pixel_format or old.pixel_format,
            )
            if new_config != old:
                self._config = new_config
                self._revision += 1
        return self

    def set_orientation(
        self,
        yaw: float = 0.0,
        pitch: float = 0.0,
        roll: float = 0.0,
    ) -> "View":
        with self._lock:
            self._orientation.set_matrix(rotation_matrix_from_euler(yaw, pitch, roll))
            self._revision += 1
        return self

    def rotate(
        self,
        yaw: float = 0.0,
        pitch: float = 0.0,
        roll: float = 0.0,
    ) -> "View":
        with self._lock:
            self._orientation.rotate_local(yaw, pitch, roll)
            self._revision += 1
        return self

    def reset(self) -> "View":
        with self._lock:
            self._orientation.reset()
            self._revision += 1
        return self

    def snapshot(self) -> ViewSnapshot:
        with self._lock:
            rotation = self._orientation.rotation_matrix.copy()
            rotation.setflags(write=False)
            return ViewSnapshot(self._config, rotation)


def _readonly_bgr(image: np.ndarray, name: str) -> np.ndarray:
    value = np.asarray(image)
    if value.ndim != 3 or value.shape[2] != 3:
        raise ValueError("{} must be an HxWx3 BGR image".format(name))
    if value.dtype != np.uint8:
        raise ValueError("{} must use uint8 BGR pixels".format(name))
    result = np.ascontiguousarray(value).copy()
    result.setflags(write=False)
    return result


def _readonly_output(image: np.ndarray) -> np.ndarray:
    output = np.ascontiguousarray(image)
    output.setflags(write=False)
    return output


class FrameBundle:
    """Independent raw camera pair with lazy stitch and projection caches."""

    def __init__(
        self,
        camera0: np.ndarray,
        camera1: np.ndarray,
        calibration: CalibrationProfile,
        *,
        index: int,
        timestamp0: Optional[float],
        timestamp1: Optional[float],
        requested_timestamp: Optional[float] = None,
        panorama_size: Tuple[int, int] = (2048, 1024),
        source: str = "unknown",
    ) -> None:
        if panorama_size[0] <= 0 or panorama_size[1] <= 0:
            raise ValueError("panorama_size must contain positive values")
        self.camera0 = _readonly_bgr(camera0, "camera0")
        self.camera1 = _readonly_bgr(camera1, "camera1")
        self.calibration = calibration
        self.index = int(index)
        self.timestamp0 = None if timestamp0 is None else float(timestamp0)
        self.timestamp1 = None if timestamp1 is None else float(timestamp1)
        self.requested_timestamp = (
            None if requested_timestamp is None else float(requested_timestamp)
        )
        self.panorama_size = tuple(map(int, panorama_size))
        self.source = str(source)
        self.sync_error_us = (
            None
            if self.timestamp0 is None or self.timestamp1 is None
            else int(round(abs(self.timestamp0 - self.timestamp1) * 1_000_000))
        )
        self._lock = threading.RLock()
        self._stage_cache: Dict[Tuple[int, int, str], EquirectangularStages] = {}
        self._render_cache: Dict[Tuple[Any, ...], np.ndarray] = {}
        self._stitch_count = 0

    @property
    def timestamp(self) -> Optional[float]:
        if self.timestamp0 is not None:
            return self.timestamp0
        if self.requested_timestamp is not None:
            return self.requested_timestamp
        return self.timestamp1

    @property
    def frame_index(self) -> int:
        return self.index

    @property
    def sync_error(self) -> Optional[float]:
        if self.sync_error_us is None:
            return None
        return self.sync_error_us / 1_000_000.0

    @property
    def stitch_count(self) -> int:
        with self._lock:
            return self._stitch_count

    def stages(
        self,
        size: Optional[Tuple[int, int]] = None,
        quality: str = "balanced",
    ) -> EquirectangularStages:
        width, height = tuple(map(int, size or self.panorama_size))
        key = (width, height, str(quality).lower())
        with self._lock:
            cached = self._stage_cache.get(key)
            if cached is not None:
                return cached
            stages = stitch_equirectangular_stages(
                self.camera0,
                self.camera1,
                self.calibration,
                width,
                height,
                quality=quality,
            )
            stages = EquirectangularStages(
                equi_1=_readonly_output(stages.equi_1),
                equi_2=_readonly_output(stages.equi_2),
                equi_blended=_readonly_output(stages.equi_blended),
            )
            self._stage_cache[key] = stages
            self._stitch_count += 1
            return stages

    @property
    def equi_1(self) -> np.ndarray:
        return self.stages().equi_1

    @property
    def equi_2(self) -> np.ndarray:
        return self.stages().equi_2

    @property
    def equi_blended(self) -> np.ndarray:
        return self.stages().equi_blended

    def render(
        self,
        view: Union[View, ViewSnapshot],
        *,
        panorama_size: Optional[Tuple[int, int]] = None,
    ) -> np.ndarray:
        snapshot = view.snapshot() if isinstance(view, View) else view
        if not isinstance(snapshot, ViewSnapshot):
            raise TypeError("view must be a View or ViewSnapshot")
        size = tuple(map(int, panorama_size or self.panorama_size))
        config = snapshot.config
        key = (
            config.projection,
            config.width,
            config.height,
            config.horizontal_fov_deg,
            config.quality,
            config.pixel_format,
            size,
            snapshot.rotation_matrix.tobytes(),
        )
        with self._lock:
            cached = self._render_cache.get(key)
            if cached is not None:
                return cached
            panorama = self.stages(size, config.quality).equi_blended
            image = render_equirectangular(
                panorama,
                OrientationState(snapshot.rotation_matrix),
                config,
            )
            output = _readonly_output(image)
            self._render_cache[key] = output
            return output


class PlayerFrame:
    """One immutable Player output plus access to every intermediate stage."""

    def __init__(self, bundle: FrameBundle, view: ViewSnapshot) -> None:
        self.bundle = bundle
        self.view = view
        self._image = bundle.render(view)

    @property
    def image(self) -> np.ndarray:
        return self._image

    def output(self, name: Union[str, FrameOutput] = FrameOutput.VIEW) -> np.ndarray:
        """Return one named BGR output without exposing renderer internals."""
        try:
            selected = FrameOutput(name)
        except ValueError as exc:
            raise ValueError(
                "output must be one of {}".format(
                    ", ".join(item.value for item in FrameOutput)
                )
            ) from exc
        if selected == FrameOutput.VIEW:
            return self.image
        if selected == FrameOutput.CAMERA0:
            return self.camera0
        if selected == FrameOutput.CAMERA1:
            return self.camera1
        if selected == FrameOutput.EQUI_1:
            return self.equi_1
        if selected == FrameOutput.EQUI_2:
            return self.equi_2
        return self.equi_blended

    @property
    def camera0(self) -> np.ndarray:
        return self.bundle.camera0

    @property
    def camera1(self) -> np.ndarray:
        return self.bundle.camera1

    @property
    def equi_1(self) -> np.ndarray:
        return self.bundle.stages(quality=self.view.config.quality).equi_1

    @property
    def equi_2(self) -> np.ndarray:
        return self.bundle.stages(quality=self.view.config.quality).equi_2

    @property
    def equi_blended(self) -> np.ndarray:
        return self.bundle.stages(quality=self.view.config.quality).equi_blended

    @property
    def timestamp(self) -> Optional[float]:
        return self.bundle.timestamp

    @property
    def frame_index(self) -> int:
        return self.bundle.frame_index

    @property
    def sync_error(self) -> Optional[float]:
        return self.bundle.sync_error


__all__ = ["FrameBundle", "PlayerFrame", "View", "ViewSnapshot"]
