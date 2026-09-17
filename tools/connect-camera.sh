#!/usr/bin/env bash
set -euo pipefail
camera=${1:-}
if [[ -z "$camera" || "$camera" == -* || "$camera" =~ [[:space:]] ]]; then
  echo 'Usage: make connect CAMERA=user@raspberrypi.local' >&2
  exit 2
fi
if command -v curl >/dev/null 2>&1 && \
   info=$(curl --noproxy '*' --fail --silent --max-time 3 http://127.0.0.1:8765/v1/info) && \
   [[ "$info" =~ \"name\"[[:space:]]*:[[:space:]]*\"RPI360\" ]] && \
   [[ "$info" =~ \"api_version\"[[:space:]]*:[[:space:]]*1[[:space:]]*[,}] ]]; then
  echo 'An RPI360 camera API is already available at http://127.0.0.1:8765.'
  echo "No new SSH tunnel was started for $camera; the existing connection is unchanged."
  echo 'Keep the existing tunnel running. To switch cameras, close that tunnel first.'
  echo 'Open http://localhost:5173 → Camera → Open live preview.'
  echo 'If the workspace is not running, start it from this checkout with: pnpm dev'
  exit 0
fi
if command -v lsof >/dev/null 2>&1 && \
   lsof -nP -iTCP@127.0.0.1:8765 -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo 'Port 8765 is occupied, but it did not respond as an RPI360 camera API.' >&2
  echo 'Check the existing tunnel and Pi service before starting another connection.' >&2
  echo 'Inspect the listener with: lsof -nP -iTCP:8765 -sTCP:LISTEN' >&2
  exit 1
fi
echo "Connecting the local device API to $camera. Keep this terminal open."
echo 'The Pi camera service must already be running; see docs/getting-started/camera.md.'
echo 'In another terminal run: pnpm dev'
echo 'Open http://localhost:5173 → Camera → Open live preview.'
echo 'No pairing code is needed. For a single-command setup, use make preview instead.'
echo 'Mac and Pi must share a LAN: WebRTC video uses a direct UDP connection.'
exec ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=6 -N -L127.0.0.1:8765:127.0.0.1:8765 "$camera"
