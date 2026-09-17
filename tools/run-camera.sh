#!/usr/bin/env bash
set -euo pipefail
base="$HOME/.local/share/rpi360"
data=${RPI360_DATA_DIR:-$base/data}
calibration=${1:-$data/calibration.json}
executable="$base/current/.venv/bin/rpi360-camera"
[[ -x "$executable" ]] || { echo 'Install on the Pi first: bash deploy/raspberry-pi/install.sh RELEASE_ID --activate' >&2; exit 1; }
[[ -f "$calibration" ]] || { echo 'Provide your rig calibration: make camera CALIBRATION=/path/to/calibration.json' >&2; exit 1; }
exec "$executable" --data-dir "$data" --calibration "$calibration"
