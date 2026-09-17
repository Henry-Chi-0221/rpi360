#!/usr/bin/env bash
set -euo pipefail
# Run on the Pi from a clean versioned source checkout. Never touches old prototypes.
repo=$(cd "$(dirname "$0")/../.." && pwd)
version=${1:?Provide a unique release identifier, e.g. v2.0.0-alpha.1+commit}
activate=${2:-}
[[ -z "$activate" || "$activate" == --activate ]] || { echo 'Expected --activate as second argument' >&2; exit 2; }
[[ "$version" =~ ^[A-Za-z0-9._+-]+$ ]] || { echo "Invalid release identifier" >&2; exit 2; }
base="$HOME/.local/share/rpi360"
release="$base/releases/$version"
[[ ! -e "$release" ]] || { echo "Release already exists: $release" >&2; exit 2; }
mkdir -p "$release" "$base/data"
cp -R "$repo/apps/camera-service" "$release/camera-service"
python3 -m venv --system-site-packages "$release/.venv"
"$release/.venv/bin/pip" install "$release/camera-service"
"$release/.venv/bin/python" -c 'import rpi360_camera; import picamera2; import av'
echo "Installed $release"
if [[ "$activate" == --activate ]]; then
  [[ ! -e "$base/current" || -L "$base/current" ]] || { echo 'current must be a symlink' >&2; exit 1; }
  ln -s "releases/$version" "$base/.current-$$"
  mv -Tf "$base/.current-$$" "$base/current"
  echo 'Active release selected. Start it with: make camera CALIBRATION=/path/to/your/calibration.json'
else
  echo "Activation: ln -sfn releases/$version $base/current"
fi
