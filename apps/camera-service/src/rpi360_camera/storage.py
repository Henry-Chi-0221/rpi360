"""Durable manifests and range-addressable, immutable recording files."""

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".json-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(value, f, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def file_info(path):
    path = Path(path)
    with path.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    return {"path": path.name, "bytes": path.stat().st_size, "sha256": digest}


class RecordingStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, recording_id):
        if not re.fullmatch(r"[a-f0-9]{32}", recording_id):
            raise ValueError("invalid recording ID")
        return self.root / (recording_id + ".r360")

    def require_space(self, minimum=256 * 1024 * 1024):
        if shutil.disk_usage(self.root).free < minimum:
            raise OSError("insufficient recording storage")

    def manifest(self, recording_id):
        return json.loads((self.directory(recording_id) / "manifest.json").read_text())

    def recordings(self):
        result = []
        for path in sorted(self.root.glob("*.r360/manifest.json"), reverse=True):
            try:
                result.append(json.loads(path.read_text()))
            except (OSError, ValueError):
                continue
        return result

    def file(self, recording_id, name):
        manifest = self.manifest(recording_id)
        if manifest["state"] not in ("complete", "recovered"):
            raise ValueError("recording is not finalized")
        allowed = {v["path"] for v in manifest["files"]} | {"manifest.json"}
        if name not in allowed or Path(name).name != name:
            raise ValueError("file is not in the recording manifest")
        directory = self.directory(recording_id)
        path = (directory / name).resolve()
        if path.parent != directory or not path.is_file():
            raise ValueError("invalid recording file")
        return path
