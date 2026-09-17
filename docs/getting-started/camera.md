# Connect a Pi and open live VR

For **iPad + Pi with no Mac**, use the [Pi-hosted workbench](ipad.md). The SSH
workflow below is for a computer running its own local workbench.

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

On macOS, this builds the workbench and installs two independent LaunchAgents:
`io.rpi360.workbench` and `io.rpi360.camera-tunnel`. Stop an existing foreground
`pnpm dev` / `make connect` first; unrelated listeners are never terminated.

Use the SSH destination that works for your Pi. The first run asks for your
normal SSH login to add a dedicated Ed25519 forwarding key, then returns when
ready. **You can close the terminal.** Neither your password nor a browser token
is stored. Subsequent starts use the saved camera address:

```sh
make preview          # start/update both services
make preview-status   # separate workbench and camera health, PIDs and log path
make preview-stop     # stop services and remove automatic login startup
```

The services start at Mac login and restart after unexpected exits. SSH checks
the existing host key and retries after network failure. The workbench is a
built snapshot in `~/Library/Application Support/RPI360/releases/`; it does not
need this checkout or a development terminal at runtime. Rebuilding does not
replace files underneath the running server. Failed update readiness restores the
previous service and checks its health before reporting the failure. Log files are under
`~/Library/Logs/RPI360/`. Keep Node.js installed at its configured location.

The Pi may be offline when the workbench opens. Local editing remains available,
and the browser retries connecting every five seconds. Video still requires a
running, calibrated Pi on the LAN. An interrupted video session can be reopened
with **Close live preview → Open live preview** after connectivity returns.
Mac logout, sleep and shutdown necessarily interrupt local availability; login
startup is configured, while actual reboot/sleep tests are not release-certified.

On other platforms, or with `node tools/preview.mjs --foreground user@raspberrypi.local`,
the launcher stays in the foreground. Keep that terminal open. macOS background
service management is the tested persistent path in this alpha.

Open **http://localhost:5173 → Open live preview**. The camera connects
automatically. Wait for **LIVE · Synced**, then drag to look around or adjust FOV,
yaw, pitch and roll. No Connect dialog is required for the standard setup.

Use **Source** to see both unstitched fisheyes, **Panorama** for the complete
scene, or **Reframe** for a viewport. Projection happens on your computer.
Use **Start recording** / **Stop recording** to capture on the Pi; closing a
preview or browser does not stop recording. Download a finished recording from
the Camera panel to edit locally. Only one live video viewer is supported, but
any connected tab or SDK can access controls and recordings.

For development, first run `make preview-stop` to free the fixed ports.
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
| API unavailable, page still opens | Check `make preview-status`, Pi service and LAN. The SSH service retries independently. |
| Page unavailable | Run `make preview-status`; inspect the workbench log. Run `make preview` to reinstall/start the selected build. |
| Port 8765 occupied, API unavailable | Use `make preview-status` first; inspect `lsof -nP -iTCP:8765 -sTCP:LISTEN` if an unrelated tunnel occupies it. The helper never kills an unknown process. |
| Workbench port 5173 occupied | A managed workbench is reused. Close an unrelated/outdated development server before installing the managed service. |
| `409` preview capacity | Close the other preview. There is one video viewer; there is no controller pairing limit. |
| Connected, no video | Permit LAN UDP and disable guest/client isolation on your network. SSH transports API traffic, not video. |
| Origin not allowed | Use `http://localhost:5173` or `http://127.0.0.1:5173`; custom origins require explicit `--origin` on the Pi. |
| Calibration missing | Start with `CALIBRATION=/path/to/your/profile.json`. VR preview needs a valid rig profile. |

## Automatic SSH connection and removal

The dedicated private key is stored under
`~/Library/Application Support/RPI360/ssh/` with permissions 0600. The public
key entry on the Pi uses OpenSSH `restrict`, a forced `/bin/false` command,
`permitopen` and `permitlisten` for `127.0.0.1:8765`. Shell, agent forwarding,
PTY and X11 access are disabled; TCP forwarding is constrained to that Pi port.
See the [OpenSSH authorized-key options](https://man.openbsd.org/sshd.8#AUTHORIZED_KEYS_FILE_FORMAT).

If the Pi account is reinstalled or the key entry is removed, reauthorize with
`node tools/preview.mjs authorize user@raspberrypi.local` using the normal SSH
login. Never disable host-key checking to repair a changed host identity.
To revoke access, remove the matching `rpi360-api-forwarding` public-key entry
from the Pi's `~/.ssh/authorized_keys`. `make preview-stop` stops local services
but preserves keys, recordings and settings; it is not server-side revocation.

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
