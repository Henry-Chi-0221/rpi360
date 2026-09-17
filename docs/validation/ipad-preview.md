# Pi-hosted iPad preview validation

Date: 2026-09-17. This records executed gateway/media tests, not an iPad
certification. The requested device is iPad Pro 11-inch (2nd generation),
iPadOS 27.0; Safari display and touch validation await that physical device.

## Deployment exercised

- Existing Pi 5 / dual IMX219 rig and its existing calibration/data directory.
- Existing camera release `ssh-flow-4ccbad56430c`; no source recordings changed.
- Dedicated Caddy 2.6.2 binary from Debian's `2.6.2-12+deb13u1` package, extracted
  into the user's application directory; no system-wide web-server installation.
- `rpi360-camera.service` owns capture/API on loopback port 8765.
- `rpi360-web.service` serves static Web assets and API on HTTPS 8443, with a
  setup/public-certificate page on HTTP 8080. IPv4 LAN listeners, explicit hosts.
- Both user services enabled; `Linger=yes` permits startup before SSH login.
- Repeated installation succeeded and preserved the same CA fingerprint.
- Browser setup page inspected in desktop Chrome; this is not an iPad result.

## Results

| Check | Observed result |
| --- | --- |
| Direct HTTPS | Pi LAN IP and `.local` hostname verified against the Pi's CA, without disabling certificate validation |
| API through gateway | Capabilities and status returned without a pairing code, token, or Mac proxy |
| WebRTC through direct Pi signaling | 230 decoded H.264 frames and 232 diagnostic messages over a 12-second observation including startup |
| Paired frame dimensions | Every decoded frame was 1440 × 540; video PTS increased monotonically |
| Synchronization at sample end | Locked, sensor-pair p95 delta 852 microseconds; this is not end-to-end latency |
| Recording preservation | Diagnostic created no recording and changed no existing bundle/calibration |
| Web process SIGKILL | PID 71483 → 71541; HTTPS/API healthy again in 3.17 seconds |
| Camera process SIGKILL | PID 71493 → 71583; API healthy again in 4.03 seconds |
| Web during camera recovery | Static workbench returned HTTP 200 while the camera restarted |
| Gateway integration suite on Pi | Trusted TLS, assets/WASM/Range, certificate-only HTTP bootstrap, cross-origin rejection, Host rejection, proxy headers and peer-subnet checks |
| Existing Web checks | 12 Web tests and 7 local workbench tests passed; TypeScript and production build passed |

The test client ran on a computer as a **direct LAN client**. Its requests and
video did not use the Mac workbench, SSH tunnel or a Mac media worker. This proves
the Pi-side deployment path, not Safari's decoding/rendering performance.
Crash tests were performed with no active recording. Boot configuration was
checked; a physical Pi reboot/power-cut test was not performed this round.

## Reproduce

On a development machine with `httpx` and `aiortc`, use the public CA certificate
from the Pi's setup page and its actual LAN address:

```sh
uv run --all-packages python tools/diagnostics/check-ipad.py \
  --url https://raspberrypi.local:8443 --ca /path/to/rpi360-ca.crt \
  --seconds 12 --output /path/to/result.json
```

Close any other live preview first. The diagnostic opens capture/preview only,
leaves recordings alone and releases its preview session when finished.

Gateway regression tests use temporary directories/ports and a simulated API:

```sh
RPI360_CADDY_BIN=/path/to/caddy uv run pytest tests/integration/test_pi_gateway.py
```

CI installs Caddy for this suite. The tests skip when no Caddy binary is available.

## Remaining iPad checks

Install/trust the Pi certificate on the actual iPad, then verify live decoded
video, GPU projection, FOV/orientation, portrait/landscape layout and touch.
Measure sustained frame rate, latency, memory, reconnection and foreground/resume.
The current canvas-to-GPU upload includes CPU copies. Browser support does not
by itself establish acceptable performance on the A12Z device. Large-file
editing/export and background transfers are separate from live-preview acceptance.
