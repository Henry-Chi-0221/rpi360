"""Unified pull-based Player for MP4 playback and RPi live capture."""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Dict, Optional, Tuple, Union

from .frames import FrameBundle, PlayerFrame, View
from .types import (
    CalibrationProfile,
    InvalidStateError,
    PathLike,
    PlayerState,
    UnsupportedOperationError,
)


class Player:
    """The only public playback/live API.

    Player is a synchronous single-consumer controller. Returned PlayerFrame
    and FrameBundle objects are independent, immutable snapshots and may be
    handed to worker threads or service queues.
    """

    def __init__(
        self,
        source: Any,
        *,
        view: View,
        paced: bool,
        speed: float,
    ) -> None:
        self._source = source
        self.view = view
        self.paced = bool(paced)
        self._speed = 1.0
        self.speed = speed
        self._state = PlayerState.NEW
        self._current_bundle: Optional[FrameBundle] = None
        self._current: Optional[PlayerFrame] = None
        self._rendered_revision = -1
        self._pending_bundle: Optional[FrameBundle] = None
        self._wall_anchor: Optional[float] = None
        self._pts_anchor: Optional[float] = None
        self._owner_thread: Optional[int] = None

    @classmethod
    def mp4(
        cls,
        input_mp4: PathLike,
        *,
        projection: str = "perspective",
        size: Tuple[int, int] = (1280, 720),
        fov: Optional[float] = None,
        quality: str = "fast",
        panorama_size: Tuple[int, int] = (2048, 1024),
        decode_size: Union[str, Tuple[int, int]] = "calibration",
        speed: float = 1.0,
        paced: bool = True,
    ) -> "Player":
        from ..playback.mp4 import Mp4Source

        return cls(
            Mp4Source(
                input_mp4,
                panorama_size=panorama_size,
                decode_size=decode_size,
            ),
            view=View(projection, size=size, fov=fov, quality=quality),
            paced=paced,
            speed=speed,
        )

    @classmethod
    def live(
        cls,
        calibration_json: PathLike,
        *,
        camera_indices: Tuple[int, int] = (0, 1),
        projection: str = "perspective",
        size: Tuple[int, int] = (1280, 720),
        fov: Optional[float] = None,
        quality: str = "fast",
        panorama_size: Tuple[int, int] = (2048, 1024),
        preview_size: Optional[Tuple[int, int]] = None,
        record_size: Optional[Tuple[int, int]] = None,
        fps: Optional[float] = None,
        camera_factory: Optional[Any] = None,
    ) -> "Player":
        from ..rpi.live import LiveSource

        source = LiveSource(
            calibration_json,
            camera_indices=camera_indices,
            panorama_size=panorama_size,
            preview_size=preview_size,
            record_size=record_size,
            fps=fps,
            camera_factory=camera_factory,
        )
        return cls(
            source,
            view=View(projection, size=size, fov=fov, quality=quality),
            paced=False,
            speed=1.0,
        )

    @property
    def source_kind(self) -> str:
        return str(self._source.kind)

    @property
    def supports_timeline(self) -> bool:
        return bool(self._source.supports_timeline)

    @property
    def state(self) -> PlayerState:
        return self._state

    @property
    def current(self) -> Optional[PlayerFrame]:
        return self._current

    @property
    def fps(self) -> float:
        return float(self._source.fps)

    @property
    def duration(self) -> Optional[float]:
        if not self.supports_timeline:
            return None
        return float(self._source.duration)

    @property
    def timeline(self) -> Optional[Dict[str, list]]:
        if not self.supports_timeline:
            return None
        return self._source.timeline

    @property
    def metadata(self) -> Optional[Dict[str, Any]]:
        if not self.supports_timeline:
            return None
        return self._source.metadata

    @property
    def calibration(self) -> CalibrationProfile:
        return self._source.calibration

    @property
    def calibration_result(self) -> Dict[str, Any]:
        return self._source.calibration_result

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, value: float) -> None:
        numeric = float(value)
        if not math.isfinite(numeric) or numeric <= 0.0:
            raise ValueError("speed must be finite and positive")
        self._speed = numeric
        self._reset_clock()

    def start(self) -> "Player":
        if self._state in {PlayerState.PLAYING, PlayerState.PAUSED}:
            return self
        self._source.start()
        self._owner_thread = threading.get_ident()
        self._state = PlayerState.PLAYING
        self._reset_clock()
        return self

    def _require_started(self) -> None:
        if self._state in {PlayerState.NEW, PlayerState.STOPPED}:
            raise InvalidStateError("Player must be started before this operation")
        if (
            self._owner_thread is not None
            and threading.get_ident() != self._owner_thread
        ):
            raise InvalidStateError(
                "Player is single-consumer; pass PlayerFrame objects across threads"
            )

    def _reset_clock(self) -> None:
        self._wall_anchor = None
        self._pts_anchor = None

    def _frame(self, bundle: FrameBundle) -> PlayerFrame:
        snapshot = self.view.snapshot()
        frame = PlayerFrame(bundle, snapshot)
        self._current_bundle = bundle
        self._current = frame
        self._rendered_revision = self.view.revision
        return frame

    def _redraw_if_dirty(self) -> Optional[PlayerFrame]:
        if (
            self._current_bundle is not None
            and self._rendered_revision != self.view.revision
        ):
            return self._frame(self._current_bundle)
        return None

    def _pace(self, bundle: FrameBundle, timeout: Optional[float]) -> bool:
        if not self.paced or self.source_kind != "mp4":
            return True
        timestamp = bundle.timestamp or 0.0
        now = time.monotonic()
        if self._wall_anchor is None or self._pts_anchor is None:
            self._wall_anchor = now
            self._pts_anchor = timestamp
            return True
        due = self._wall_anchor + (timestamp - self._pts_anchor) / self.speed
        remaining = due - now
        if remaining <= 0.0:
            return True
        if timeout is not None and remaining > timeout:
            time.sleep(max(0.0, timeout))
            return False
        time.sleep(remaining)
        return True

    def next(self, timeout: Optional[float] = 0.03) -> Optional[PlayerFrame]:
        self._require_started()
        if timeout is not None and float(timeout) < 0.0:
            raise ValueError("timeout must be non-negative or None")
        redrawn = self._redraw_if_dirty()
        if redrawn is not None:
            return redrawn
        if self._state == PlayerState.PAUSED:
            if self._pending_bundle is not None:
                bundle = self._pending_bundle
                self._pending_bundle = None
                return self._frame(bundle)
            if timeout:
                time.sleep(float(timeout))
            return None
        if self._state == PlayerState.ENDED:
            return None
        try:
            bundle = self._pending_bundle
            if bundle is None:
                bundle = self._source.read(timeout=timeout)
            if bundle is None:
                if self.source_kind == "mp4":
                    self._state = PlayerState.ENDED
                return None
            if not self._pace(bundle, timeout):
                self._pending_bundle = bundle
                return None
            self._pending_bundle = None
            return self._frame(bundle)
        except TimeoutError:
            return None
        except BaseException:
            self._state = PlayerState.FAILED
            raise

    def play(self) -> "Player":
        self._require_started()
        if self._state == PlayerState.ENDED:
            self.restart()
        self._state = PlayerState.PLAYING
        self._reset_clock()
        return self

    def pause(self) -> "Player":
        self._require_started()
        self._state = PlayerState.PAUSED
        return self

    def toggle_pause(self) -> "Player":
        if self._state in {PlayerState.PAUSED, PlayerState.ENDED}:
            return self.play()
        return self.pause()

    def rotate(
        self, yaw: float = 0.0, pitch: float = 0.0, roll: float = 0.0
    ) -> "Player":
        self.view.rotate(yaw, pitch, roll)
        return self

    def set_orientation(
        self, yaw: float = 0.0, pitch: float = 0.0, roll: float = 0.0
    ) -> "Player":
        """Set an absolute Mapper-compatible orientation in degrees."""
        self.view.set_orientation(yaw, pitch, roll)
        return self

    def configure(
        self,
        projection: Optional[str] = None,
        *,
        size: Optional[Tuple[int, int]] = None,
        fov: Optional[float] = None,
        quality: Optional[str] = None,
    ) -> "Player":
        self.view.configure(projection, size=size, fov=fov, quality=quality)
        return self

    def reset_view(self) -> "Player":
        self.view.reset()
        return self

    def _require_timeline(self, operation: str) -> None:
        self._require_started()
        if not self.supports_timeline:
            raise UnsupportedOperationError(
                "{} is unavailable for a live Player".format(operation)
            )

    def seek(self, timestamp: float) -> "Player":
        self._require_timeline("seek")
        was_paused = self._state == PlayerState.PAUSED
        self._source.seek(timestamp)
        self._current_bundle = None
        self._current = None
        self._pending_bundle = self._source.read()
        self._state = PlayerState.PAUSED if was_paused else PlayerState.PLAYING
        self._reset_clock()
        return self

    def seek_by(self, seconds: float) -> "Player":
        self._require_timeline("seek_by")
        current = (
            self._current.timestamp
            if self._current is not None and self._current.timestamp is not None
            else 0.0
        )
        return self.seek(current + float(seconds))

    def step(self, frames: int = 1) -> Optional[PlayerFrame]:
        self._require_timeline("step")
        timeline = self._source.timeline["camera_0"]
        current_index = self._current.frame_index if self._current is not None else -1
        target_index = max(0, min(current_index + int(frames), len(timeline) - 1))
        self._source.seek(timeline[target_index])
        bundle = self._source.read()
        self._pending_bundle = None
        self._state = PlayerState.PAUSED
        self._reset_clock()
        return None if bundle is None else self._frame(bundle)

    def restart(self) -> "Player":
        self._require_timeline("restart")
        return self.seek(0.0)

    def start_recording(self, output: PathLike, *, overwrite: bool = False) -> Any:
        self._require_started()
        if self.source_kind != "live":
            raise UnsupportedOperationError(
                "recording is only available for a live Player"
            )
        return self._source.start_recording(output, overwrite=overwrite)

    def inspect(self) -> Dict[str, Any]:
        """Return source information without exposing its implementation."""
        if hasattr(self._source, "inspect"):
            return self._source.inspect()
        return {
            "source": self.source_kind,
            "fps": self.fps,
            "calibration_result": self.calibration_result,
        }

    def stop(self) -> None:
        if self._state == PlayerState.STOPPED:
            return
        self._source.stop()
        self._state = PlayerState.STOPPED
        self._owner_thread = None
        self._pending_bundle = None
        self._reset_clock()

    def __enter__(self) -> "Player":
        return self.start()

    def __exit__(self, *args: Any) -> None:
        self.stop()


__all__ = ["Player"]
