# Contributing

Use Python 3.9 or newer and install the development environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
ruff check .
pytest
```

Rendering changes must preserve the Mapper coordinate convention, BGR channel
order, seam behavior, and the existing golden tests. Do not commit recordings,
local calibration results, or calibration work directories outside the curated
`assets/` and `calibration/` paths.

RPi camera changes also require a manual two-camera calibration, live-preview,
recording, and playback test with Picamera2.

Changes to `hardware/cad/` must retain the CERN-OHL-P-2.0 licence and applicable
notices. Add a dated modification notice when conveying a modified hardware
design.
