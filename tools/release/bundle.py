"""Package local alpha artifacts and checksums without publishing a release."""

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "dist"
OUT.mkdir(exist_ok=True)


def archive(name, files):
    path = OUT / name
    with zipfile.ZipFile(
        path, "w", compression=zipfile.ZIP_STORED, allowZip64=True
    ) as z:
        for file in files:
            if not file.is_file():
                raise FileNotFoundError(file)
            z.write(file, str(file.relative_to(ROOT)))
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.file_digest(path.open("rb"), "sha256").hexdigest(),
    }


recipes = sorted((ROOT / "demos/recipes").glob("*.json"))
videos = [ROOT / "demos/outputs" / (p.stem + ".mp4") for p in recipes]
reports = sorted((ROOT / "demos/outputs").glob("*.json"))
artifacts = [
    archive(
        "rpi360-2.0.0-alpha.1-demos.zip",
        [
            *videos,
            *reports,
            *recipes,
            *sorted((ROOT / "demos/posters").glob("*.jpg")),
            ROOT / "demos/sources.manifest.json",
            ROOT / "demos/README.md",
            ROOT / "LICENSE-MEDIA",
        ],
    )
]
artifacts.append(
    archive(
        "rpi360-2.0.0-alpha.1-web.zip",
        sorted(p for p in (ROOT / "apps/web/dist").rglob("*") if p.is_file()),
    )
)
manifest = {
    "version": "2.0.0-alpha.1",
    "status": "alpha-not-production-certified",
    "git_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip(),
    "validation_report": "docs/validation/status.md",
    "artifacts": artifacts,
}
(OUT / "artifacts.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(artifacts, indent=2))
