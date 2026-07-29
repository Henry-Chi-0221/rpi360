"""RPI360 MP4 metadata, timestamp pairing, and persistent decoding.

The media layer knows nothing about stitching or views.  It identifies logical
cameras exclusively from the track IDs embedded in RPI360 metadata and returns
OpenCV-compatible ``uint8 BGR`` frame pairs.
"""

from __future__ import annotations

import copy
import math
import subprocess
from bisect import bisect_left
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Tuple,
    Union,
)

import numpy as np

from ..common.metadata import (
    _run,
    _run_json,
    calibration_from_metadata,
    find_camera_tracks,
    probe_media,
    read_r360_metadata,
    require_executable,
    stream_descriptor,
)
from ..common.types import (
    CalibrationProfile,
    ExternalToolError,
    MetadataError,
    PathLike,
)


class RPI360Recording:
    """Validated RPI360 recording metadata and timestamp-aware frame access."""

    def __init__(
        self,
        path: Path,
        metadata: Mapping[str, Any],
        media_probe: Mapping[str, Any],
    ) -> None:
        self.path = path
        self.metadata = dict(metadata)
        self.calibration = calibration_from_metadata(metadata)
        from ..common.metadata import read_embedded_calibration_result

        self.calibration_result = read_embedded_calibration_result(
            path, r360_metadata=metadata
        )
        tracks = find_camera_tracks(metadata, media_probe.get("streams", []))
        self.camera0 = stream_descriptor(tracks["camera_0"])
        self.camera1 = stream_descriptor(tracks["camera_1"])
        candidates = [
            value for value in (self.camera0["fps"], self.camera1["fps"]) if value > 0.0
        ]
        if not candidates:
            candidates = [
                float(metadata["streams"][name].get("fps", 0.0))
                for name in ("camera_0", "camera_1")
                if float(metadata["streams"][name].get("fps", 0.0)) > 0.0
            ]
        if not candidates:
            raise MetadataError("neither camera track contains a valid FPS")
        self.fps = min(candidates)
        format_info = media_probe.get("format", {})
        durations = [
            value
            for value in (
                self.camera0["duration"],
                self.camera1["duration"],
            )
            if value > 0.0
        ]
        self.duration = (
            min(durations)
            if durations
            else float(format_info.get("duration", 0.0) or 0.0)
        )
        self._timestamps_by_stream: Optional[Dict[int, List[float]]] = None

    @classmethod
    def open(cls, path: PathLike) -> "RPI360Recording":
        media_path = Path(path)
        if media_path.suffix.lower() != ".mp4":
            raise ValueError("RPI360 input must be an .mp4 file")
        media_probe = probe_media(media_path)
        metadata = read_r360_metadata(media_path, media_probe=media_probe)
        return cls(media_path, metadata, media_probe)

    @property
    def timeline(self) -> Dict[str, List[float]]:
        self._load_timestamps()
        assert self._timestamps_by_stream is not None
        return {
            "camera_0": list(self._timestamps_by_stream[self.camera0["stream_index"]]),
            "camera_1": list(self._timestamps_by_stream[self.camera1["stream_index"]]),
        }

    def _load_timestamps(self) -> None:
        if self._timestamps_by_stream is not None:
            return
        payload = _run_json(
            [
                require_executable("ffprobe"),
                "-v",
                "error",
                "-show_packets",
                "-select_streams",
                "v",
                "-show_entries",
                "packet=stream_index,pts_time,dts_time",
                "-of",
                "json",
                str(self.path),
            ]
        )
        target_indices = {
            self.camera0["stream_index"],
            self.camera1["stream_index"],
        }
        timestamps: Dict[int, List[float]] = {index: [] for index in target_indices}
        for packet in payload.get("packets", []):
            try:
                index = int(packet["stream_index"])
            except (KeyError, TypeError, ValueError):
                continue
            if index not in timestamps:
                continue
            raw = packet.get("pts_time", packet.get("dts_time"))
            try:
                timestamp = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(timestamp):
                timestamps[index].append(timestamp)
        for index, values in timestamps.items():
            # MP4 packets are stored in decode order when B-frames are present.
            # Sorting packet PTS restores presentation order without the very
            # expensive ffprobe -show_frames decode pass.
            values[:] = sorted(set(values))
            if not values:
                raise MetadataError(
                    "video stream {} has no usable frame timestamps".format(index)
                )
        self._timestamps_by_stream = timestamps

    @staticmethod
    def _nearest(values: List[float], requested: float) -> float:
        position = bisect_left(values, requested)
        candidates = []
        if position < len(values):
            candidates.append(values[position])
        if position > 0:
            candidates.append(values[position - 1])
        return min(candidates, key=lambda value: abs(value - requested))

    def nearest_frame_timestamps(self, timestamp: float) -> Tuple[float, float]:
        requested = float(timestamp)
        if not math.isfinite(requested) or requested < 0.0:
            raise ValueError("timestamp must be finite and non-negative")
        if self.duration > 0.0 and requested > self.duration + 1e-6:
            raise ValueError(
                "timestamp {:.6f}s exceeds recording duration {:.6f}s".format(
                    requested, self.duration
                )
            )
        timeline = self.timeline
        return (
            self._nearest(timeline["camera_0"], requested),
            self._nearest(timeline["camera_1"], requested),
        )

    def decode_frame_at(
        self,
        stream: Mapping[str, Any],
        timestamp: float,
        output_size: Optional[Tuple[int, int]] = None,
    ) -> np.ndarray:
        width, height = _validated_decode_size(output_size, stream)
        command = [
            require_executable("ffmpeg"),
            "-v",
            "error",
            "-ss",
            "{:.9f}".format(timestamp),
            "-i",
            str(self.path),
            "-map",
            "0:{}".format(int(stream["stream_index"])),
            "-frames:v",
            "1",
            "-an",
            "-sn",
        ]
        if output_size is not None:
            command.extend(
                [
                    "-vf",
                    "scale={}:{}:flags=fast_bilinear".format(width, height),
                ]
            )
        command.extend(
            [
                "-f",
                "rawvideo",
                "-pix_fmt",
                "bgr24",
                "pipe:1",
            ]
        )
        completed = _run(command)
        expected = width * height * 3
        if len(completed.stdout) < expected:
            raise ExternalToolError(
                "decoded stream {} returned {} bytes; expected {}".format(
                    stream["stream_index"],
                    len(completed.stdout),
                    expected,
                )
            )
        return (
            np.frombuffer(completed.stdout[:expected], dtype=np.uint8)
            .reshape(height, width, 3)
            .copy()
        )

    def get_frame_pair(
        self,
        timestamp: float,
        decode_sizes: Optional[
            Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]
        ] = None,
    ) -> Tuple[np.ndarray, np.ndarray, float, float]:
        timestamp0, timestamp1 = self.nearest_frame_timestamps(timestamp)
        size0, size1 = decode_sizes or (None, None)
        return (
            self.decode_frame_at(self.camera0, timestamp0, size0),
            self.decode_frame_at(self.camera1, timestamp1, size1),
            timestamp0,
            timestamp1,
        )

    def inspect(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "duration": self.duration,
            "fps": self.fps,
            "camera_0": dict(self.camera0),
            "camera_1": dict(self.camera1),
            "metadata": dict(self.metadata),
            "calibration_result": dict(self.calibration_result),
        }


def _read_exact(stream: Any, byte_count: int) -> bytes:
    chunks = []
    remaining = byte_count
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _validated_decode_size(
    output_size: Optional[Tuple[int, int]],
    descriptor: Mapping[str, Any],
) -> Tuple[int, int]:
    if output_size is None:
        return int(descriptor["width"]), int(descriptor["height"])
    if len(output_size) != 2:
        raise ValueError("decode size must contain width and height")
    width, height = map(int, output_size)
    if width <= 0 or height <= 0:
        raise ValueError("decode size must contain positive values")
    return width, height


class _TrackDecoder:
    def __init__(
        self,
        recording: RPI360Recording,
        descriptor: Mapping[str, Any],
        timestamps: List[float],
        start_index: int,
        output_size: Optional[Tuple[int, int]] = None,
    ) -> None:
        self.recording = recording
        self.descriptor = descriptor
        self.timestamps = timestamps
        self.index = start_index
        self.output_size = output_size
        self.width, self.height = _validated_decode_size(output_size, descriptor)
        self.process: Optional[subprocess.Popen] = None

    def start(self) -> None:
        if self.index >= len(self.timestamps):
            return
        timestamp = self.timestamps[self.index]
        command = [
            require_executable("ffmpeg"),
            "-v",
            "error",
            "-i",
            str(self.recording.path),
            "-ss",
            "{:.9f}".format(timestamp),
            "-map",
            "0:{}".format(int(self.descriptor["stream_index"])),
            "-an",
            "-sn",
            "-vsync",
            "0",
        ]
        if self.output_size is not None:
            command.extend(
                [
                    "-vf",
                    "scale={}:{}:flags=fast_bilinear".format(self.width, self.height),
                ]
            )
        command.extend(
            [
                "-f",
                "rawvideo",
                "-pix_fmt",
                "bgr24",
                "pipe:1",
            ]
        )
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def read(self) -> Optional[Tuple[np.ndarray, float]]:
        if self.index >= len(self.timestamps):
            return None
        if self.process is None:
            self.start()
        assert self.process is not None and self.process.stdout is not None
        expected = self.width * self.height * 3
        payload = _read_exact(self.process.stdout, expected)
        if len(payload) != expected:
            return_code = self.process.poll()
            detail = ""
            if self.process.stderr is not None:
                detail = (
                    self.process.stderr.read().decode("utf-8", errors="replace").strip()
                )
            if return_code not in (None, 0):
                raise ExternalToolError(
                    "ffmpeg stream {} ended with {}: {}".format(
                        self.descriptor["stream_index"],
                        return_code,
                        detail,
                    )
                )
            return None
        timestamp = self.timestamps[self.index]
        self.index += 1
        frame = (
            np.frombuffer(payload, dtype=np.uint8)
            .reshape(self.height, self.width, 3)
            .copy()
        )
        return frame, timestamp

    def close(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.stdout is not None:
            process.stdout.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        if process.stderr is not None:
            process.stderr.close()


class DualTrackReader:
    """Persistent native-rate decoder paired on camera-0 presentation times."""

    def __init__(
        self,
        recording: RPI360Recording,
        *,
        start: float = 0.0,
        end: Optional[float] = None,
        decode_sizes: Optional[
            Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]
        ] = None,
    ) -> None:
        self.recording = recording
        self.start_time = float(start)
        self.end_time = None if end is None else float(end)
        self.decode_sizes = decode_sizes or (None, None)
        if len(self.decode_sizes) != 2:
            raise ValueError("decode_sizes must contain camera 0 and camera 1")
        _validated_decode_size(self.decode_sizes[0], recording.camera0)
        _validated_decode_size(self.decode_sizes[1], recording.camera1)
        if self.start_time < 0.0 or not math.isfinite(self.start_time):
            raise ValueError("start must be finite and non-negative")
        if self.end_time is not None and (
            not math.isfinite(self.end_time) or self.end_time <= self.start_time
        ):
            raise ValueError("end must be finite and greater than start")
        self._decoder0: Optional[_TrackDecoder] = None
        self._decoder1: Optional[_TrackDecoder] = None
        self._camera1_previous: Optional[Tuple[np.ndarray, float]] = None
        self._camera1_next: Optional[Tuple[np.ndarray, float]] = None
        self._started = False

    def start(self) -> "DualTrackReader":
        if self._started:
            return self
        timeline = self.recording.timeline
        index0 = bisect_left(timeline["camera_0"], self.start_time)
        index1 = max(0, bisect_left(timeline["camera_1"], self.start_time) - 1)
        self._decoder0 = _TrackDecoder(
            self.recording,
            self.recording.camera0,
            timeline["camera_0"],
            index0,
            self.decode_sizes[0],
        )
        self._decoder1 = _TrackDecoder(
            self.recording,
            self.recording.camera1,
            timeline["camera_1"],
            index1,
            self.decode_sizes[1],
        )
        self._decoder0.start()
        self._decoder1.start()
        self._camera1_previous = self._decoder1.read()
        self._camera1_next = self._decoder1.read()
        self._started = True
        return self

    def read(
        self,
    ) -> Optional[Tuple[np.ndarray, np.ndarray, float, float]]:
        if not self._started:
            self.start()
        assert self._decoder0 is not None and self._decoder1 is not None
        camera0 = self._decoder0.read()
        if camera0 is None:
            return None
        frame0, timestamp0 = camera0
        if self.end_time is not None and timestamp0 >= self.end_time:
            return None

        while self._camera1_next is not None and self._camera1_next[1] <= timestamp0:
            self._camera1_previous = self._camera1_next
            self._camera1_next = self._decoder1.read()
        candidates = [
            candidate
            for candidate in (
                self._camera1_previous,
                self._camera1_next,
            )
            if candidate is not None
        ]
        if not candidates:
            return None
        frame1, timestamp1 = min(
            candidates, key=lambda candidate: abs(candidate[1] - timestamp0)
        )
        return frame0, frame1.copy(), timestamp0, timestamp1

    def close(self) -> None:
        if self._decoder0 is not None:
            self._decoder0.close()
        if self._decoder1 is not None:
            self._decoder1.close()
        self._decoder0 = None
        self._decoder1 = None
        self._camera1_previous = None
        self._camera1_next = None
        self._started = False

    def __enter__(self) -> "DualTrackReader":
        return self.start()

    def __exit__(self, *args: Any) -> None:
        self.close()


class Mp4Source:
    """Timestamp-aware frame source used internally by :class:`Player`."""

    kind = "mp4"
    supports_timeline = True

    def __init__(
        self,
        input_mp4: PathLike,
        *,
        panorama_size: Tuple[int, int] = (2048, 1024),
        decode_size: Union[str, Tuple[int, int]] = "calibration",
    ) -> None:
        self.path = Path(input_mp4)
        self.panorama_size = tuple(map(int, panorama_size))
        self.decode_size = decode_size
        self.recording: Optional[RPI360Recording] = None
        self.reader: Optional[DualTrackReader] = None
        self.next_timestamp = 0.0
        self.index = 0

    def start(self) -> "Mp4Source":
        if self.recording is None:
            self.recording = RPI360Recording.open(self.path)
        return self

    def _require_recording(self) -> RPI360Recording:
        if self.recording is None:
            raise RuntimeError("MP4 source is not started")
        return self.recording

    def _decode_sizes(
        self,
    ) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]:
        recording = self._require_recording()
        if isinstance(self.decode_size, str):
            mode = self.decode_size.lower()
            if mode == "native":
                return None, None
            if mode == "calibration":
                return (
                    (
                        recording.calibration.camera0.width,
                        recording.calibration.camera0.height,
                    ),
                    (
                        recording.calibration.camera1.width,
                        recording.calibration.camera1.height,
                    ),
                )
            raise ValueError(
                "decode_size must be 'native', 'calibration', or (width, height)"
            )
        size = tuple(map(int, self.decode_size))
        if len(size) != 2 or size[0] <= 0 or size[1] <= 0:
            raise ValueError("decode_size must contain positive width and height")
        return size, size

    @property
    def fps(self) -> float:
        return self._require_recording().fps

    @property
    def duration(self) -> float:
        return self._require_recording().duration

    @property
    def timeline(self) -> Dict[str, List[float]]:
        return self._require_recording().timeline

    @property
    def calibration(self) -> CalibrationProfile:
        return self._require_recording().calibration

    @property
    def calibration_result(self) -> Dict[str, Any]:
        return copy.deepcopy(self._require_recording().calibration_result)

    @property
    def metadata(self) -> Dict[str, Any]:
        return copy.deepcopy(self._require_recording().metadata)

    def inspect(self) -> Dict[str, Any]:
        result = self._require_recording().inspect()
        sizes = self._decode_sizes()
        recording = self._require_recording()
        native_sizes = (
            (recording.camera0["width"], recording.camera0["height"]),
            (recording.camera1["width"], recording.camera1["height"]),
        )
        result.update(
            {
                "source": "mp4",
                "processing_sizes": [
                    list(size or native)
                    for size, native in zip(sizes, native_sizes)
                ],
                "pixel_format": "bgr24",
                "panorama_size": list(self.panorama_size),
            }
        )
        return result

    def read(self, timeout: Optional[float] = None) -> Optional[Any]:
        del timeout
        from ..common.frames import FrameBundle

        recording = self._require_recording()
        if self.reader is None:
            self.reader = DualTrackReader(
                recording,
                start=self.next_timestamp,
                decode_sizes=self._decode_sizes(),
            ).start()
        pair = self.reader.read()
        if pair is None:
            return None
        camera0, camera1, timestamp0, timestamp1 = pair
        bundle = FrameBundle(
            camera0,
            camera1,
            recording.calibration,
            index=self.index,
            timestamp0=timestamp0,
            timestamp1=timestamp1,
            requested_timestamp=self.next_timestamp,
            panorama_size=self.panorama_size,
            source=str(self.path),
        )
        self.index += 1
        self.next_timestamp = timestamp0 + 1e-9
        return bundle

    def seek(self, timestamp: float) -> "Mp4Source":
        recording = self._require_recording()
        requested = float(timestamp)
        if not math.isfinite(requested):
            raise ValueError("seek timestamp must be finite")
        requested = max(0.0, min(requested, max(0.0, recording.duration)))
        if self.reader is not None:
            self.reader.close()
        self.reader = None
        self.next_timestamp = requested
        self.index = bisect_left(recording.timeline["camera_0"], requested)
        return self

    def read_at(self, timestamp: float) -> Any:
        from ..common.frames import FrameBundle

        recording = self._require_recording()
        frame0, frame1, timestamp0, timestamp1 = recording.get_frame_pair(
            timestamp, decode_sizes=self._decode_sizes()
        )
        return FrameBundle(
            frame0,
            frame1,
            recording.calibration,
            index=bisect_left(recording.timeline["camera_0"], timestamp0),
            timestamp0=timestamp0,
            timestamp1=timestamp1,
            requested_timestamp=float(timestamp),
            panorama_size=self.panorama_size,
            source=str(self.path),
        )

    def stop(self) -> None:
        if self.reader is not None:
            self.reader.close()
        self.reader = None
        self.recording = None


__all__ = [
    "DualTrackReader",
    "Mp4Source",
    "RPI360Recording",
]
