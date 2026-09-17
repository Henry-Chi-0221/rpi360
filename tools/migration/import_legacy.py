"""Lossless legacy dual-track import; unknown capture synchronization stays unknown."""

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import av
from rpi360.core import convert_calibration
from rpi360_camera.storage import atomic_json, file_info


def migrate(source, destination):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    with av.open(str(source)) as inp:
        metadata = json.loads(inp.metadata.get("rpi360", "{}"))
        if not metadata.get("calibration"):
            raise ValueError("Missing legacy RPI360 calibration metadata")
        calibration = metadata["calibration"]
        for i in (0, 1):
            c = calibration[f"camera_{i}"]
            s = metadata["streams"][f"camera_{i}"]
            c.setdefault("width", s["width"])
            c.setdefault("height", s["height"])
        calibration = convert_calibration(calibration)
    destination.mkdir(parents=True)
    manifest = {
        "schema_version": 2,
        "id": uuid.uuid4().hex,
        "state": "recording",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "clock": {
            "epoch": "legacy-media-clock",
            "origin_sensor_ns": None,
            "unit": "microseconds",
        },
        "streams": [],
        "calibration": "calibration.json",
        "sync": {"method": "unknown", "tolerance_us": None},
        "files": [],
    }
    atomic_json(destination / "calibration.json", calibration)
    atomic_json(destination / "manifest.json", manifest)
    try:
        for i in (0, 1):
            name = f"camera{i}.mp4"
            frame_count = 0
            origin = None
            last = None
            with (
                av.open(str(source)) as inp,
                av.open(
                    str(destination / name),
                    "w",
                    format="mp4",
                    options={
                        "movflags": "frag_keyframe+empty_moov+default_base_moof",
                        "frag_duration": "1000000",
                    },
                ) as out,
                (destination / f"camera{i}.frames.jsonl").open("x") as index,
            ):
                track = next(
                    s
                    for s in inp.streams.video
                    if s.id == metadata["streams"][f"camera_{i}"]["track_id"]
                )
                stream = out.add_stream_from_template(track)
                for packet in inp.demux(track):
                    if packet.pts is None:
                        continue
                    if origin is None:
                        origin = min(
                            packet.dts if packet.dts is not None else packet.pts,
                            packet.pts,
                        )
                    original_pts = packet.pts
                    pts_us = round(original_pts * packet.time_base * 1e6)
                    media_pts_us = round((packet.pts - origin) * packet.time_base * 1e6)
                    packet.pts -= origin
                    if packet.dts is not None:
                        packet.dts -= origin
                    packet.stream = stream
                    out.mux(packet)
                    index.write(
                        json.dumps(
                            {
                                "pts_us": pts_us,
                                "media_pts_us": media_pts_us,
                                "sensor_ns": None,
                                "exposure_us": None,
                                "sequence": None,
                                "sync_ready": None,
                                "legacy": True,
                            }
                        )
                        + "\n"
                    )
                    frame_count += 1
                    last = max(last if last is not None else pts_us, pts_us)
                if origin is None:
                    raise ValueError("Empty legacy video track")
                manifest["streams"].append(
                    {
                        "camera": i,
                        "path": name,
                        "width": track.width,
                        "height": track.height,
                        "codec": "h264",
                        "frames": frame_count,
                        "media_start_offset_us": round(origin * track.time_base * 1e6),
                        "last_pts_us": last,
                    }
                )
            with av.open(str(destination / name)) as check:
                if sum(1 for _ in check.decode(video=0)) != frame_count:
                    raise ValueError("Remux verification failed")
        manifest["state"] = "complete"
    except Exception as e:
        manifest["state"] = "recovery_required"
        manifest["error"] = str(e)
        atomic_json(destination / "manifest.json", manifest)
        raise
    manifest["files"] = [
        file_info(p)
        for p in sorted(destination.iterdir())
        if p.is_file() and p.name != "manifest.json"
    ]
    atomic_json(destination / "manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source")
    p.add_argument("destination")
    a = p.parse_args()
    print(json.dumps(migrate(a.source, a.destination), indent=2))
