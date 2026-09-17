"""Create a portable bundle without recompressing source video."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("bundle", type=Path)
p.add_argument("output", type=Path)
a = p.parse_args()
m = json.loads((a.bundle / "manifest.json").read_text())
if m["state"] not in ("complete", "recovered"):
    raise ValueError("finalize or recover the recording first")
with zipfile.ZipFile(
    a.output, "x", compression=zipfile.ZIP_STORED, allowZip64=True
) as z:
    for entry in m["files"]:
        path = (a.bundle / entry["path"]).resolve()
        if path.parent != a.bundle.resolve():
            raise ValueError("unsafe bundle path")
        with path.open("rb") as f:
            checksum = hashlib.file_digest(f, "sha256").hexdigest()
        if checksum != entry["sha256"]:
            raise ValueError("checksum mismatch: " + entry["path"])
        z.write(path, entry["path"])
    z.write(a.bundle / "manifest.json", "manifest.json")
