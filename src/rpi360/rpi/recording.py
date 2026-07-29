"""Recording lifecycle and atomic dual-track MP4 finalization."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Tuple

from ..common.metadata import (
    calibration_to_metadata,
    find_camera_tracks,
    probe_media,
    require_executable,
    stream_descriptor,
    write_recording_metadata,
)
from ..common.types import PathLike


@dataclass(frozen=True)
class RecordingStatus:
    output: Path
    active: bool
    frame_count: int
    duration: float


class RecordingHandle:
    """Idempotent handle for an in-progress live recording."""

    def __init__(
        self,
        output: Path,
        stop_callback: Callable[[], Path],
        status_callback: Callable[[], RecordingStatus],
    ) -> None:
        self._output = output
        self._stop_callback = stop_callback
        self._status_callback = status_callback
        self._result: Optional[Path] = None
        self._error: Optional[BaseException] = None
        self._final_status: Optional[RecordingStatus] = None
        self._lock = threading.Lock()

    @property
    def status(self) -> RecordingStatus:
        return self._final_status or self._status_callback()

    @property
    def active(self) -> bool:
        return self.status.active

    @property
    def result(self) -> Optional[Path]:
        return self._result

    def stop(self) -> Path:
        with self._lock:
            if self._error is not None:
                raise self._error
            if self._result is None:
                try:
                    self._result = self._stop_callback()
                except BaseException as exc:
                    self._error = exc
                    raise
                status = self._status_callback()
                self._final_status = RecordingStatus(
                    output=self._result,
                    active=False,
                    frame_count=status.frame_count,
                    duration=status.duration,
                )
            return self._result

    def __enter__(self) -> "RecordingHandle":
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()


def mux_recording(
    track_paths: Tuple[Path, Path],
    output_path: PathLike,
    *,
    fps: float,
    calibration: Any,
    calibration_result: Mapping[str, Any],
    overwrite: bool = False,
) -> Path:
    """Mux camera tracks as IDs 1/2, add both tags, then atomically publish."""
    output = Path(output_path)
    if output.suffix.lower() != ".mp4":
        raise ValueError("recording output must use an .mp4 suffix")
    if output.exists() and not overwrite:
        raise FileExistsError(str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=".{}.muxing-".format(output.stem),
        suffix=".mp4",
        dir=str(output.parent),
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    command = [require_executable("ffmpeg"), "-v", "error", "-y"]
    for track in track_paths:
        if track.suffix.lower() == ".h264":
            command.extend(["-r", "{:.9g}".format(fps)])
        command.extend(["-i", str(track)])
    command.extend(
        [
            "-map",
            "0:v:0",
            "-map",
            "1:v:0",
            "-c",
            "copy",
            "-map_metadata",
            "-1",
            "-streamid",
            "0:1",
            "-streamid",
            "1:2",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
    )
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "could not mux dual video tracks: {}".format(
                    completed.stderr.decode("utf-8", errors="replace").strip()
                )
            )
        descriptors = {
            descriptor["track_id"]: descriptor
            for descriptor in map(
                stream_descriptor,
                [
                    item
                    for item in probe_media(temporary).get("streams", [])
                    if item.get("codec_type") == "video"
                ],
            )
        }
        if 1 not in descriptors or 2 not in descriptors:
            raise RuntimeError("mux did not preserve camera track IDs 1 and 2")
        metadata = calibration_to_metadata(
            calibration,
            camera0_track_id=1,
            camera1_track_id=2,
            camera0_stream=descriptors[1],
            camera1_stream=descriptors[2],
        )
        write_recording_metadata(temporary, metadata, calibration_result)
        find_camera_tracks(temporary)
        os.replace(str(temporary), str(output))
    finally:
        if temporary.exists():
            temporary.unlink()
    return output


def discard_recording_directory(directory: Optional[Path]) -> None:
    if directory is not None and directory.is_dir():
        shutil.rmtree(directory)


def recording_directory() -> Path:
    return Path(tempfile.mkdtemp(prefix="rpi360-recording-"))


__all__ = [
    "RecordingHandle",
    "RecordingStatus",
    "discard_recording_directory",
    "mux_recording",
    "recording_directory",
]
