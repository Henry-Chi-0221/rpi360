# Camera service on Raspberry Pi

Use Raspberry Pi OS with two detected cameras and a Picamera2/libcamera version
providing `SyncMode`, `SyncReady` and `SensorTimestamp`. The inspected rig used
Picamera2 0.3.37 and libcamera 0.7.2. Use the OS packages for camera integration.

```sh
sudo apt install python3-venv python3-picamera2 python3-av ffmpeg
bash deploy/raspberry-pi/install.sh v2.0.0-alpha.1-local
```

Copy your rig's calibration to the separate application data directory. Keep the
original calibration and recordings elsewhere as backups. The included example
calibration belongs to one particular physical rig; it is not a universal preset.

For a development session, launch the installed binary in the foreground:

```sh
~/.local/share/rpi360/releases/v2.0.0-alpha.1-local/.venv/bin/rpi360-camera \
  --data-dir ~/.local/share/rpi360/data \
  --calibration ~/.local/share/rpi360/data/calibration.json \
  --origin http://localhost:5173
```

On the development computer:

```sh
ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -N -L 8765:127.0.0.1:8765 USER@CAMERA
pnpm dev
```

Choose **Connect camera**, keep `/api`, and enter the local pairing code printed
by the service. **Camera → Open live preview** starts capture. Wait for the
synchronization indicator before recording. The browser can close without
stopping a recording; reconnect to stop/finalize it and download the bundle.

The service defaults to 1640×1232, 30 fps, 8 Mbps per camera, retaining full sensor
field of view. These are requested settings, not a sustained-performance promise.
The preview initially uses two 820×616 images in one 1640×616 H.264 track.

## Trusted HTTPS deployment

For direct LAN access, supply `--host 0.0.0.0 --cert CERT --key KEY`. Certificates
must be trusted by each client and name the camera hostname. A reverse proxy may
serve the built Web app and proxy `/api` to loopback, yielding one HTTPS origin.
Keep bearer headers, Range headers and WebRTC SDP intact. WebRTC media uses
negotiated LAN UDP connectivity; HTTPS alone does not forward media packets.

For a private development CA, generate a camera certificate whose SAN includes
its hostname, install the CA using the operating system's certificate settings,
and verify ordinary HTTPS without interstitials before pairing. Do not disable
certificate validation. Installing trust is an explicit deployment step, not a
side effect performed by application JavaScript. Public HTTPS origins may require
Chrome's local-network permission; test that prompt in the actual deployment.

## Versioned deployment and rollback

Release code lives under `releases/`; calibration, recordings and tokens live in
`data/`. After validation, switch `current` and restart the service. The supplied
systemd user unit binds loopback by default; adapt the unit for a trusted TLS
endpoint. Retain the previous release directory. Rolling back changes executable
code only, never deletes or rolls back user data. Do not point this installer at
an existing prototype directory.

## Serve the workbench from the Pi

Build with `pnpm wasm && pnpm build`, copy `apps/web/dist` into the versioned
release directory, and pass `--web-root /path/to/release/web` to the camera service.
The built workbench calls `/v1` on its own origin. Network listening still requires
`--cert` and `--key` with a certificate trusted by the client device.
`GET /v1/settings` and `PUT /v1/settings` expose revision-checked exposure and white
balance controls; provide the last read revision when updating both cameras.
