"""Calibration-result JSON and RPI360 MP4 metadata contracts."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Union,
)

import numpy as np

from .types import (
    CalibrationProfile,
    DualCameraIntrinsics,
    ExternalToolError,
    MetadataError,
    PathLike,
    validate_calibration,
)

CALIBRATION_RESULT_TAG = "rpi360_calibration_result"
CALIBRATION_RESULT_SCHEMA_VERSION = 1
CALIBRATION_STATE_INTRINSICS = "intrinsics_complete"
CALIBRATION_STATE_COMPLETE = "complete"
R360_METADATA_TAG = "rpi360"
R360_SCHEMA_VERSION = 1


def require_executable(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise ExternalToolError(
            "{} is required for RPI360 operations but was not found in PATH".format(
                name
            )
        )
    return executable


def _run(command: Sequence[str]) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ExternalToolError(
            "command failed ({}): {}".format(completed.returncode, detail)
        )
    return completed


def _run_json(command: Sequence[str]) -> Dict[str, Any]:
    completed = _run(command)
    try:
        return json.loads(completed.stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ExternalToolError("external tool returned invalid JSON") from exc


def probe_media(path: PathLike) -> Dict[str, Any]:
    media_path = Path(path)
    if not media_path.is_file():
        raise FileNotFoundError(str(media_path))
    return _run_json(
        [
            require_executable("ffprobe"),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(media_path),
        ]
    )


def _parse_track_id(value: Any) -> int:
    if isinstance(value, int):
        return value
    try:
        return int(str(value), 0)
    except ValueError as exc:
        raise MetadataError("invalid MP4 track id {!r}".format(value)) from exc


def _fps_from_stream(stream: Mapping[str, Any]) -> float:
    value = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    try:
        numerator, denominator = str(value).split("/", 1)
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else 0.0
    except (TypeError, ValueError):
        return 0.0


def stream_descriptor(stream: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "track_id": _parse_track_id(stream["id"]),
        "stream_index": int(stream["index"]),
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": _fps_from_stream(stream),
        "codec": stream.get("codec_name"),
        "duration": float(stream.get("duration", 0.0) or 0.0),
    }


def calibration_to_metadata(
    calibration: CalibrationProfile,
    *,
    camera0_track_id: int,
    camera1_track_id: int,
    camera0_stream: Optional[Mapping[str, Any]] = None,
    camera1_stream: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    validate_calibration(calibration)

    def stream_payload(
        camera: Any,
        track_id: int,
        supplied: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        values = supplied or {}
        return {
            "track_id": int(track_id),
            "width": int(values.get("width", camera.width)),
            "height": int(values.get("height", camera.height)),
            "fps": float(values.get("fps", 0.0)),
        }

    return {
        "schema_version": R360_SCHEMA_VERSION,
        "streams": {
            "camera_0": stream_payload(
                calibration.camera0, camera0_track_id, camera0_stream
            ),
            "camera_1": stream_payload(
                calibration.camera1, camera1_track_id, camera1_stream
            ),
        },
        "calibration": calibration.to_dict(),
    }


def validate_r360_metadata(metadata: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(metadata, Mapping):
        raise MetadataError("RPI360 metadata must be a JSON object")
    try:
        version = int(metadata["schema_version"])
        streams = metadata["streams"]
        calibration = metadata["calibration"]
    except (KeyError, TypeError, ValueError) as exc:
        raise MetadataError(
            "metadata must contain schema_version, streams, and calibration"
        ) from exc
    if version != R360_SCHEMA_VERSION:
        raise MetadataError(
            "unsupported RPI360 schema_version {}; expected {}".format(
                version, R360_SCHEMA_VERSION
            )
        )
    if not isinstance(streams, Mapping) or not isinstance(calibration, Mapping):
        raise MetadataError("streams and calibration must be JSON objects")

    normalized = json.loads(json.dumps(metadata))
    seen_track_ids = set()
    for camera_name in ("camera_0", "camera_1"):
        try:
            stream = normalized["streams"][camera_name]
            track_id = int(stream["track_id"])
            width = int(stream["width"])
            height = int(stream["height"])
            fps = float(stream["fps"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MetadataError(
                "invalid {} stream metadata".format(camera_name)
            ) from exc
        if track_id < 0 or track_id in seen_track_ids:
            raise MetadataError(
                "camera track IDs must be distinct non-negative integers"
            )
        if width <= 0 or height <= 0 or not math.isfinite(fps) or fps < 0.0:
            raise MetadataError(
                "stream width/height must be positive and fps non-negative"
            )
        stream.update(track_id=track_id, width=width, height=height, fps=fps)
        seen_track_ids.add(track_id)

    CalibrationProfile.from_dict(normalized["calibration"], normalized["streams"])
    return normalized


def calibration_from_metadata(metadata: Mapping[str, Any]) -> CalibrationProfile:
    validated = validate_r360_metadata(metadata)
    return CalibrationProfile.from_dict(
        validated["calibration"], streams=validated["streams"]
    )


def find_camera_tracks(
    metadata_or_path: Union[Mapping[str, Any], PathLike],
    available_tracks: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Resolve logical cameras by MP4 track ID, never stream order."""
    if isinstance(metadata_or_path, (str, os.PathLike)):
        probe = probe_media(metadata_or_path)
        metadata = read_r360_metadata(metadata_or_path, media_probe=probe)
        tracks = probe.get("streams", [])
    else:
        metadata = validate_r360_metadata(metadata_or_path)
        tracks = list(available_tracks) if available_tracks is not None else None

    expected = {
        name: int(metadata["streams"][name]["track_id"])
        for name in ("camera_0", "camera_1")
    }
    if tracks is None:
        return expected

    by_id: Dict[int, Mapping[str, Any]] = {}
    for stream in tracks:
        if stream.get("codec_type") == "video" and "id" in stream:
            by_id[_parse_track_id(stream["id"])] = stream
    missing = [name for name, track_id in expected.items() if track_id not in by_id]
    if missing:
        raise MetadataError(
            "metadata references video tracks not present in MP4: " + ", ".join(missing)
        )
    return {name: dict(by_id[track_id]) for name, track_id in expected.items()}


def read_r360_metadata(
    path: PathLike,
    *,
    media_probe: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    probe = dict(media_probe) if media_probe is not None else probe_media(path)
    tags: MutableMapping[str, Any] = {}
    tags.update(probe.get("format", {}).get("tags", {}) or {})
    for stream in probe.get("streams", []):
        for key, value in (stream.get("tags", {}) or {}).items():
            tags.setdefault(key, value)

    raw = _tag_value(tags, R360_METADATA_TAG)
    if raw is None:
        raise MetadataError(
            "{} does not contain the required {!r} MP4 metadata tag".format(
                path, R360_METADATA_TAG
            )
        )
    try:
        metadata = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MetadataError("embedded RPI360 metadata is not valid JSON") from exc
    return validate_r360_metadata(metadata)


def write_r360_metadata(path: PathLike, metadata: Mapping[str, Any]) -> Path:
    """Atomically embed validated metadata into an existing MP4."""
    media_path = Path(path)
    if not media_path.is_file():
        raise FileNotFoundError(str(media_path))
    normalized = validate_r360_metadata(metadata)
    compact_json = json.dumps(normalized, separators=(",", ":"), sort_keys=True)
    with tempfile.NamedTemporaryFile(
        prefix=".{}.metadata-".format(media_path.stem),
        suffix=media_path.suffix,
        dir=str(media_path.parent),
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
    try:
        _run(
            [
                require_executable("ffmpeg"),
                "-v",
                "error",
                "-y",
                "-i",
                str(media_path),
                "-map",
                "0",
                "-c",
                "copy",
                "-map_metadata",
                "0",
                "-metadata",
                "{}={}".format(R360_METADATA_TAG, compact_json),
                "-movflags",
                "use_metadata_tags",
                str(temporary_path),
            ]
        )
        if read_r360_metadata(temporary_path) != normalized:
            raise MetadataError("metadata verification failed after MP4 remux")
        os.replace(str(temporary_path), str(media_path))
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return media_path


def validate_calibration_document(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a calibration-result at either supported completion stage."""
    if not isinstance(value, Mapping):
        raise MetadataError("calibration result must be a JSON object")
    try:
        version = int(value["schema_version"])
        calibration = value["calibration"]
    except (KeyError, TypeError, ValueError) as exc:
        raise MetadataError(
            "calibration result requires schema_version and calibration"
        ) from exc
    if version != CALIBRATION_RESULT_SCHEMA_VERSION:
        raise MetadataError(
            "unsupported calibration-result schema_version {}; expected {}".format(
                version, CALIBRATION_RESULT_SCHEMA_VERSION
            )
        )
    if not isinstance(calibration, Mapping):
        raise MetadataError("calibration must be a JSON object")
    diagnostics = value.get("diagnostics", {})
    if not isinstance(diagnostics, Mapping):
        raise MetadataError("diagnostics must be a JSON object")
    intrinsics = DualCameraIntrinsics.from_dict(calibration)
    has_rotation = "R_cam1_to_cam0" in calibration
    if has_rotation:
        normalized_calibration = CalibrationProfile.from_dict(calibration).to_dict()
        state = CALIBRATION_STATE_COMPLETE
    else:
        normalized_calibration = intrinsics.to_dict()
        state = CALIBRATION_STATE_INTRINSICS
    normalized = json.loads(json.dumps(value))
    normalized["schema_version"] = version
    normalized["calibration_state"] = state
    normalized["calibration"] = normalized_calibration
    normalized["diagnostics"] = json.loads(json.dumps(diagnostics))
    return normalized


def calibration_document_from_intrinsics(
    intrinsics: DualCameraIntrinsics,
    diagnostics: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return validate_calibration_document(
        {
            "schema_version": CALIBRATION_RESULT_SCHEMA_VERSION,
            "calibration_state": CALIBRATION_STATE_INTRINSICS,
            "calibration": intrinsics.to_dict(),
            "diagnostics": {"intrinsics": dict(diagnostics or {})},
        }
    )


def calibration_intrinsics_from_document(
    result: Mapping[str, Any],
) -> DualCameraIntrinsics:
    normalized = validate_calibration_document(result)
    return DualCameraIntrinsics.from_dict(normalized["calibration"])


def validate_calibration_result(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a complete result suitable for Player, recording, and MP4."""
    normalized = validate_calibration_document(value)
    if normalized["calibration_state"] != CALIBRATION_STATE_COMPLETE:
        raise MetadataError(
            "calibration-result contains camera intrinsics but rig calibration "
            "is not complete"
        )
    return normalized


def calibration_result_from_profile(
    profile: CalibrationProfile,
    diagnostics: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return validate_calibration_result(
        {
            "schema_version": CALIBRATION_RESULT_SCHEMA_VERSION,
            "calibration_state": CALIBRATION_STATE_COMPLETE,
            "calibration": profile.to_dict(),
            "diagnostics": dict(diagnostics or {}),
        }
    )


def calibration_profile_from_result(
    result: Mapping[str, Any],
) -> CalibrationProfile:
    normalized = validate_calibration_result(result)
    return CalibrationProfile.from_dict(normalized["calibration"])


def load_calibration_result(path: PathLike) -> Dict[str, Any]:
    calibration_path = Path(path)
    if calibration_path.suffix.lower() != ".json":
        raise ValueError("Player.live calibration must be a .json file")
    try:
        payload = json.loads(calibration_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MetadataError("calibration-result JSON is invalid") from exc
    return validate_calibration_result(payload)


def load_calibration_document(path: PathLike) -> Dict[str, Any]:
    calibration_path = Path(path)
    if calibration_path.suffix.lower() != ".json":
        raise ValueError("calibration result input must be a .json file")
    try:
        payload = json.loads(calibration_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MetadataError("calibration-result JSON is invalid") from exc
    return validate_calibration_document(payload)


def _atomic_write_json(
    path: PathLike,
    value: Mapping[str, Any],
    *,
    overwrite: bool,
) -> Path:
    output = Path(path)
    if output.suffix.lower() != ".json":
        raise ValueError("calibration output must use a .json suffix")
    if output.exists() and not overwrite:
        raise FileExistsError(str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=".{}.".format(output.name),
        suffix=".tmp",
        dir=str(output.parent),
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(str(temporary), str(output))
    finally:
        if temporary.exists():
            temporary.unlink()
    return output


def update_calibration_document(
    path: PathLike,
    result: Mapping[str, Any],
) -> Path:
    return _atomic_write_json(
        path,
        validate_calibration_document(result),
        overwrite=True,
    )


def save_calibration_result(
    path: PathLike,
    result: Mapping[str, Any],
    *,
    overwrite: bool = False,
) -> Path:
    normalized = validate_calibration_result(result)
    return _atomic_write_json(path, normalized, overwrite=overwrite)


def _combined_tags(path: PathLike) -> MutableMapping[str, Any]:
    probe = probe_media(path)
    tags: MutableMapping[str, Any] = {}
    tags.update(probe.get("format", {}).get("tags", {}) or {})
    for stream in probe.get("streams", []):
        for key, value in (stream.get("tags", {}) or {}).items():
            tags.setdefault(key, value)
    return tags


def _tag_value(tags: Mapping[str, Any], wanted: str) -> Optional[Any]:
    for key, value in tags.items():
        if str(key).lower() == wanted.lower():
            return value
    return None


def _profiles_match(first: CalibrationProfile, second: CalibrationProfile) -> bool:
    return all(
        np.allclose(left, right, rtol=0.0, atol=1e-9)
        for left, right in (
            (first.camera0.K, second.camera0.K),
            (first.camera0.D, second.camera0.D),
            (first.camera1.K, second.camera1.K),
            (first.camera1.D, second.camera1.D),
            (first.R_cam1_to_cam0, second.R_cam1_to_cam0),
        )
    ) and (
        first.camera0.width,
        first.camera0.height,
        first.camera0.fisheye_fov_deg,
        first.camera1.width,
        first.camera1.height,
        first.camera1.fisheye_fov_deg,
    ) == (
        second.camera0.width,
        second.camera0.height,
        second.camera0.fisheye_fov_deg,
        second.camera1.width,
        second.camera1.height,
        second.camera1.fisheye_fov_deg,
    )


def read_embedded_calibration_result(
    path: PathLike,
    *,
    r360_metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Read the full tag, or synthesize a compatible result for legacy MP4s."""
    metadata = dict(r360_metadata or read_r360_metadata(path))
    legacy_profile = calibration_from_metadata(metadata)
    raw = _tag_value(_combined_tags(path), CALIBRATION_RESULT_TAG)
    if raw is None:
        return calibration_result_from_profile(
            legacy_profile, {"source": "legacy-rpi360-tag"}
        )
    try:
        full_result = validate_calibration_result(json.loads(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise MetadataError(
            "embedded rpi360_calibration_result is not valid JSON"
        ) from exc
    full_profile = calibration_profile_from_result(full_result)
    if not _profiles_match(legacy_profile, full_profile):
        raise MetadataError(
            "rpi360 and rpi360_calibration_result tags contain different "
            "K/D/R calibration values"
        )
    return full_result


def write_recording_metadata(
    path: PathLike,
    r360_metadata: Mapping[str, Any],
    calibration_result: Mapping[str, Any],
) -> Path:
    """Atomically write and verify both MP4 metadata tags."""
    media_path = Path(path)
    if not media_path.is_file():
        raise FileNotFoundError(str(media_path))
    normalized_metadata = validate_r360_metadata(r360_metadata)
    normalized_result = validate_calibration_result(calibration_result)
    legacy_profile = CalibrationProfile.from_dict(
        normalized_metadata["calibration"], normalized_metadata["streams"]
    )
    if not _profiles_match(
        legacy_profile, calibration_profile_from_result(normalized_result)
    ):
        raise MetadataError(
            "cannot write inconsistent RPI360 and calibration-result metadata"
        )
    legacy_json = json.dumps(normalized_metadata, separators=(",", ":"), sort_keys=True)
    result_json = json.dumps(normalized_result, separators=(",", ":"), sort_keys=True)
    with tempfile.NamedTemporaryFile(
        prefix=".{}.metadata-".format(media_path.stem),
        suffix=media_path.suffix,
        dir=str(media_path.parent),
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    try:
        completed = subprocess.run(
            [
                require_executable("ffmpeg"),
                "-v",
                "error",
                "-y",
                "-i",
                str(media_path),
                "-map",
                "0",
                "-c",
                "copy",
                "-map_metadata",
                "0",
                "-metadata",
                "{}={}".format(R360_METADATA_TAG, legacy_json),
                "-metadata",
                "{}={}".format(CALIBRATION_RESULT_TAG, result_json),
                "-movflags",
                "use_metadata_tags",
                str(temporary),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            raise ExternalToolError(
                "could not write MP4 metadata: {}".format(
                    completed.stderr.decode("utf-8", errors="replace").strip()
                )
            )
        if read_r360_metadata(temporary) != normalized_metadata:
            raise MetadataError("RPI360 metadata verification failed")
        if (
            read_embedded_calibration_result(
                temporary, r360_metadata=normalized_metadata
            )
            != normalized_result
        ):
            raise MetadataError("calibration-result metadata verification failed")
        os.replace(str(temporary), str(media_path))
    finally:
        if temporary.exists():
            temporary.unlink()
    return media_path


__all__ = [
    "CALIBRATION_STATE_COMPLETE",
    "CALIBRATION_STATE_INTRINSICS",
    "CALIBRATION_RESULT_SCHEMA_VERSION",
    "CALIBRATION_RESULT_TAG",
    "R360_METADATA_TAG",
    "R360_SCHEMA_VERSION",
    "calibration_document_from_intrinsics",
    "calibration_from_metadata",
    "calibration_intrinsics_from_document",
    "calibration_profile_from_result",
    "calibration_result_from_profile",
    "calibration_to_metadata",
    "find_camera_tracks",
    "load_calibration_document",
    "load_calibration_result",
    "probe_media",
    "read_r360_metadata",
    "read_embedded_calibration_result",
    "require_executable",
    "save_calibration_result",
    "stream_descriptor",
    "update_calibration_document",
    "validate_calibration_document",
    "validate_calibration_result",
    "validate_r360_metadata",
    "write_r360_metadata",
    "write_recording_metadata",
]
