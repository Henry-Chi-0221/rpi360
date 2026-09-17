#!/usr/bin/env bash
set -euo pipefail
camera=${1:-}
if [[ -z "$camera" || "$camera" == -* || "$camera" =~ [[:space:]] ]]; then
  echo 'Usage: make connect CAMERA=user@raspberrypi.local' >&2
  exit 2
fi
echo "Connecting the local device API to $camera. Keep this terminal open."
echo 'The Pi camera service must already be running; see docs/getting-started/camera.md.'
echo 'In another terminal run: pnpm dev'
echo 'Open http://localhost:5173 → Connect camera → address /api → Camera → Open live preview.'
echo 'Use the Pi pairing code once; leave it empty when reconnecting the same tab.'
echo 'Mac and Pi must share a LAN: WebRTC video uses a direct UDP connection.'
exec ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=6 -N -L127.0.0.1:8765:127.0.0.1:8765 "$camera"
