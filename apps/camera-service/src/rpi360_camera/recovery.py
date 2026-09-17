"""Recover committed fragmented-MP4 data into a NEW bundle; never overwrite input."""

import json
import shutil
import struct
import uuid
from pathlib import Path

import av

from .storage import atomic_json, file_info


def committed_prefix(path):
    """Only retain complete moof/mdat pairs; incomplete tails are excluded."""
    size = path.stat().st_size
    pos = 0
    last = 0
    fragment = False
    with path.open("rb") as f:
        while pos + 8 <= size:
            f.seek(pos)
            header = f.read(8)
            length, kind = struct.unpack(">I4s", header)
            header_size = 8
            if length == 1:
                if pos + 16 > size:
                    break
                length = struct.unpack(">Q", f.read(8))[0]
                header_size = 16
            if length == 0:
                length = size - pos
            if length < header_size or pos + length > size:
                break
            if kind == b"moof":
                fragment = True
            if kind == b"mdat" and fragment:
                last = pos + length
                fragment = False
            pos += length
    if not last:
        raise ValueError(f"{path.name}: no complete media fragment")
    return last


def recover(source, destination):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if source == destination or source in destination.parents:
        raise ValueError("recovery output must be separate from source")
    if destination.exists():
        raise FileExistsError(destination)
    manifest = json.loads((source / "manifest.json").read_text())
    destination.mkdir(parents=True)
    manifest["recovered_from"] = manifest["id"]
    manifest["id"] = uuid.uuid4().hex
    manifest["state"] = "recovering"
    manifest["files"] = []
    atomic_json(destination / "manifest.json", manifest)
    for stream in manifest["streams"]:
        name = stream["path"]
        if Path(name).name != name:
            raise ValueError("unsafe source path")
        source_file = (source / name).resolve()
        if source_file.parent != source:
            raise ValueError("source symlink escapes bundle")
        keep = committed_prefix(source_file)
        with source_file.open("rb") as inp, (destination / name).open("xb") as out:
            while keep:
                chunk = inp.read(min(1024 * 1024, keep))
                out.write(chunk)
                keep -= len(chunk)
        pts = []
        with av.open(str(destination / name)) as video:
            for packet in video.demux(video=0):
                if packet.pts is not None:
                    pts.append(round(packet.pts * packet.time_base * 1e6))
        if not pts:
            raise ValueError("recovered track has no packets")
        stream["frames"] = len(pts)
        stream["last_pts_us"] = max(pts) + stream.get("media_start_offset_us", 0)
        index = f"camera{stream['camera']}.frames.jsonl"
        valid = set(pts)
        retained = 0
        with (source / index).open() as inp, (destination / index).open("x") as out:
            for line in inp:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    break
                if item["media_pts_us"] in valid:
                    out.write(line)
                    retained += 1
        stream["metadata_frames"] = retained
    if manifest.get("calibration"):
        name = manifest["calibration"]
        path = (source / name).resolve()
        if path.parent != source:
            raise ValueError("unsafe calibration path")
        shutil.copyfile(path, destination / name)
    manifest["state"] = "recovered"
    manifest.pop("error", None)
    manifest["files"] = [
        file_info(p)
        for p in sorted(destination.iterdir())
        if p.is_file() and p.name != "manifest.json"
    ]
    atomic_json(destination / "manifest.json", manifest)
    return manifest
