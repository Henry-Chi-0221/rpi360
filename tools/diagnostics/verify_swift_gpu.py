"""Compare Swift/Metal and native export against the same public source fixture."""

import json
import struct
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="rpi360-swift-golden-") as tmp:
    folder = Path(tmp)
    image = Image.open(ROOT / "apps/web/public/demo/lake.jpg").convert("RGBA")
    pixels = image.tobytes()
    source = folder / "source.rgba"
    source.write_bytes(pixels)
    calibration = ROOT / "apps/web/public/demo/calibration.json"
    project = {
        "schema_version": 2,
        "id": "swift-golden",
        "source_id": "lake",
        "duration_us": 1_000_000,
        "alignment_us": None,
        "keyframes": [
            {
                "time_us": 0,
                "linear": True,
                "view": {
                    "orientation": [0, 0, 0, 1],
                    "horizontal_fov_deg": 90,
                    "projection": "perspective",
                    "spin_deg": 0,
                },
            }
        ],
        "time_remap": [{"output_us": 0, "source_us": 0}],
    }
    project_path = folder / "project.json"
    project_path.write_text(json.dumps(project))
    native = subprocess.check_output(
        [
            str(ROOT / "target/release/rpi360-render"),
            "--pipe",
            str(calibration),
            str(project_path),
            str(image.width),
            str(image.height),
            "320",
            "180",
            "true",
        ],
        input=struct.pack("<q", 0) + pixels,
    )
    output = folder / "swift.rgba"
    subprocess.run(
        [
            "swift",
            "run",
            "--package-path",
            str(ROOT / "packages/apple-sdk"),
            "RPI360Smoke",
            str(calibration),
            str(source),
            str(image.width),
            str(image.height),
            str(output),
        ],
        check=True,
    )
    if native != output.read_bytes() or len(native) != 320 * 180 * 4:
        raise SystemExit("Swift/native renderer mismatch")
    print(f"Swift/native GPU parity: all {len(native):,} RGBA bytes match")
