# Connect a Pi and open live VR

The normal workflow uses your existing SSH login. There are no pairing codes,
accounts, saved browser tokens or exclusive controller registration. The camera
API listens on Pi loopback, and the local workbench reaches it through SSH.
Keep both devices on the same LAN: video uses a direct WebRTC UDP connection.

## 1. On the Pi

Use Raspberry Pi OS with Picamera2/libcamera providing `SyncMode`, `SyncReady`
and `SensorTimestamp`. The inspected Pi 5 rig uses Picamera2 0.3.37 and libcamera
0.7.2 with two IMX219 fisheye cameras. Confirm both cameras are detected first.

For this pre-release, clone the v2 branch (the default branch may still be v1):

```sh
git clone --branch codex/rpi360-v2 https://github.com/Henry-Chi-0221/rpi360.git
cd rpi360
sudo apt install python3-venv python3-picamera2 python3-av ffmpeg
bash deploy/raspberry-pi/install.sh "$(git rev-parse --short HEAD)" --activate
make camera CALIBRATION=/path/to/your/calibration.json
```

Replace the calibration path with **your physical rig's profile**. Keep this
terminal running. The example profile in Git is not a universal calibration.
The installer creates a separate release and selects it only after an import
smoke check; it never overwrites an existing release, prototype or recording.
Run the installer once per new commit, after stopping any older camera service.
Omit `--activate` when staging a release without switching the selected version.

Recordings default to `~/.local/share/rpi360/data`. Set `RPI360_DATA_DIR` to reuse
an existing data directory. For future launches, you may copy your calibration
to `~/.local/share/rpi360/data/calibration.json` and simply run `make camera`.
The service does not print or require a pairing code.

## 2. On your computer

Clone the same branch, enter the checkout and complete the one-time
[Web build setup](../../README.md#try-it-without-a-camera). Then:

```sh
cd /path/to/rpi360
make preview CAMERA=your_username@raspberrypi.local
```

Use the SSH destination that works for your Pi: hostname, `.local` name or LAN
IP. Enter your normal SSH password if prompted; an SSH key also works.
The command starts both the tunnel and workbench and prints the browser URL.
Leave it running. Ctrl+C stops only the local processes it started; it does not
stop a Pi recording. Existing working services are reused and left untouched.
Reusing a tunnel does not change its destination; close it first to switch Pis.

Open **http://localhost:5173 → Camera → Open live preview**. The camera connects
automatically. Wait for **LIVE · Synced**, then drag to look around or adjust FOV,
yaw, pitch and roll. No Connect dialog is required for the standard setup.

Use **Source** to see both unstitched fisheyes, **Panorama** for the complete
scene, or **Reframe** for a viewport. Projection happens on your computer.
Use **Start recording** / **Stop recording** to capture on the Pi; closing a
preview or browser does not stop recording. Download a finished recording from
the Camera panel to edit locally. Only one live video viewer is supported, but
any connected tab or SDK can access controls and recordings.

For separate terminal management, `make connect CAMERA=...` starts only SSH;
`pnpm dev` starts only the workbench. Both commands run from the repository root.

## Troubleshooting

```sh
curl --fail http://127.0.0.1:8765/v1/info
curl --fail http://localhost:5173/api/v1/status
```

The first must report `name: RPI360`, `api_version: 1`, `access_mode: local`.
The second verifies the complete browser proxy path without credentials.

| Symptom | Action |
| --- | --- |
| `No rule to make target preview` | Enter the rpi360 checkout first; update it if it predates this command. |
| Update the Pi camera service / old `401` | Update **both** checkouts, install and start the new Pi release, then reload the workbench. Old browser credentials are no longer used. |
| API unavailable | Start `make camera` on the Pi and check your SSH destination. |
| Port 8765 occupied, API unavailable | Inspect `lsof -nP -iTCP:8765 -sTCP:LISTEN` and the Pi service. The helper never kills an unknown process. |
| Workbench port 5173 occupied | Reuse the workbench at that URL, or close an unrelated/outdated server first. |
| `409` preview capacity | Close the other preview. There is one video viewer; there is no controller pairing limit. |
| Connected, no video | Permit LAN UDP and disable guest/client isolation on your network. SSH transports API traffic, not video. |
| Origin not allowed | Use `http://localhost:5173` or `http://127.0.0.1:5173`; custom origins require explicit `--origin` on the Pi. |
| Calibration missing | Start with `CALIBRATION=/path/to/your/profile.json`. VR preview needs a valid rig profile. |

## Optional direct HTTPS deployment

This is separate from the simple SSH workflow. An iPad cannot use a Mac's
loopback address. For direct LAN access, serve the built workbench on a trusted
HTTPS origin on the Pi and configure one operator-managed API token:

```sh
umask 077
python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > /path/to/api-token
rpi360-camera --host 0.0.0.0 --cert /path/to/cert.pem --key /path/to/key.pem \
  --api-token-file /path/to/api-token --web-root /path/to/apps/web/dist \
  --data-dir /path/to/data --calibration /path/to/calibration.json
```

Build the workbench with `pnpm wasm && pnpm build`. Trust the certificate on
each client and use a certificate naming the camera hostname; do not disable
certificate validation. In this mode the Connect dialog requests the configured
API token. It is held in memory, not saved in browser storage. SDKs accept the
same optional token. Rotate the file and restart the service to replace it;
stop/finalize recording before restarting. Keep token files private (0600).
Browser LAN permission and Apple device behavior still need deployment-specific
validation. Do not proxy unauthenticated loopback access onto a public interface.

## Unattended service and updates

The supplied systemd user unit uses the selected `current` release and separate
data directory. After the foreground setup works:

```sh
mkdir -p ~/.config/systemd/user
cp deploy/raspberry-pi/systemd/rpi360-camera.service ~/.config/systemd/user/
# Place your calibration at ~/.local/share/rpi360/data/calibration.json first.
# Stop the foreground service before starting systemd.
systemctl --user daemon-reload
systemctl --user enable --now rpi360-camera
```

Use `journalctl --user -u rpi360-camera` for logs. To start before SSH login,
configure user lingering with `sudo loginctl enable-linger "$USER"`.
For updates, finalize recording, stop the service, install/activate a new unique
release, then restart. Rollback selects a previous release without changing data.
Old `authorized-clients.json` files are ignored and left intact; they need no
recovery/reset operation. The workbench removes obsolete saved RPI360 tokens.

The candidate source mode is 1640×1232 at 30 fps and 8 Mbps per camera; preview
uses a 1440×540 H.264 pair. These are requested settings, not a sustained
performance claim. See [measured validation](../validation/status.md).
