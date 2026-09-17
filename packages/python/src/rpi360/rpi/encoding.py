"""Shared dual-camera encoder lifecycle."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Tuple

from ..common.types import InvalidStateError
from .camera import CameraDevice


class DualEncoderSession:
    """Start and stop two Picamera2 encoders together with rollback."""

    def __init__(
        self,
        devices: Tuple[CameraDevice, CameraDevice],
        tracks: Tuple[Path, Path],
    ) -> None:
        self.devices = devices
        self.tracks = tracks
        self.started_at: Optional[Tuple[float, float]] = None

    @property
    def active(self) -> bool:
        return self.started_at is not None

    def start(self) -> "DualEncoderSession":
        if self.active:
            return self

        def start_one(device: CameraDevice, track: Path) -> float:
            started = time.monotonic()
            device.start_recording(track)
            return started

        try:
            with ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="rpi360-encoder"
            ) as executor:
                futures = (
                    executor.submit(start_one, self.devices[0], self.tracks[0]),
                    executor.submit(start_one, self.devices[1], self.tracks[1]),
                )
                started_at = (futures[0].result(), futures[1].result())
        except BaseException:
            for device in self.devices:
                device.stop_recording()
            raise
        self.started_at = started_at
        return self

    def stop(self) -> None:
        if not self.active:
            return
        with ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="rpi360-encoder"
        ) as executor:
            futures = [
                executor.submit(device.stop_recording) for device in self.devices
            ]
            for future in futures:
                future.result()
        self.started_at = None

    def require_started_at(self) -> Tuple[float, float]:
        if self.started_at is None:
            raise InvalidStateError("dual encoder session is not active")
        return self.started_at


__all__ = ["DualEncoderSession"]
