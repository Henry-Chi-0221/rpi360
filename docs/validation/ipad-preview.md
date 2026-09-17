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
Crash tests were performed with no active recording. The initial gateway round
checked boot configuration only. A subsequent normal reboot was executed as
recorded below; physical power interruption remains untested.

## Responsive navigation follow-up

The previous layout hid the library/camera sidebar below 850 px and the icon
rail below 600 px, leaving phone users without a preview entrance. The updated
workbench keeps **Open live preview** in the header and provides **Camera**,
**Library**, **Effects** and **Export** navigation at narrow widths. Camera
controls open in a scrollable panel with a visible Close button.

Executed with desktop Chrome at 390 × 844 and 834 × 1194 CSS pixels:

- Opened the real Pi stream from the header; observed decoded camera video and
  **LIVE · Synced**, then closed and reopened the preview successfully.
- Adjusted FOV from 90° to 110° while the live session remained active.
- Checked the Camera panel and phone Effects navigation. Recording controls
  remain visible in live mode; the editing timeline and keyframe/effect hints
  are hidden until preview closes.
- Released the test preview afterwards so it does not occupy the single viewer
  slot. No recording was created by these UI checks.

This browser UI check used the existing localhost camera proxy. It supplements,
rather than replaces, the direct Pi HTTPS/media test above and is **not a
physical iPad/Safari test**. The same built HTML, JS and CSS were deployed to the
Pi and compared byte-for-byte through certificate-validated HTTPS. Only the Web
service restarted; the camera process PID was unchanged. TypeScript, the
production build, 12 Web tests and 7 workbench-server tests passed.

## Tailscale follow-up

Executed on 2026-09-17 with Pi and Mac connected to the same tailnet. The iPad
was visible as an online peer; its browser was not operated by this diagnostic.

- `https://raspberrypi:8443`, the Pi's Tailscale IPv4 and IPv6 addresses, and its
  original LAN address returned HTTP 200 with CA and hostname/IP verification.
- The short-name origin could access the API. Untrusted origins returned 403.
  The HTTP setup page contained working Tailscale links and only the public CA.
- With **both SDP offers and answers limited to Tailscale ICE candidates**, a
  12-second run decoded 217 H.264 frames at 1440 × 540 and received 359 frame
  diagnostics. Video PTS were monotonic; sensor sync was locked. This rules out
  silent LAN media fallback, but is not an off-site latency or Safari test.
- The test session was released. No source recording was created or changed.
- The camera PID and Pi CA fingerprint were unchanged after gateway/Web updates.
- Gateway tests cover LAN-only and opt-in tailnet modes, real TLS for the short
  name, allowed and rejected peer sources, origin/Host checks, Range transfers,
  the certificate-only HTTP port and dual-stack listeners: 13 passed, with the
  tailnet-alias case intentionally skipped in LAN-only mode.
- TypeScript, production build, 12 Web tests and 7 workbench-server tests passed.

Debian Caddy 2.6 attempted overlapping IPv4/IPv6 QUIC UDP listeners during the
first deployment. Readiness failed and restored the previous configuration.
The gateway now explicitly uses HTTP/1.1 and HTTP/2; WebRTC video retains its
separate UDP transport. The dual-stack gateway test covers this startup case.
Caddy's automatic `*.ts.net` certificate delegation is not used: this mode
serves the short MagicDNS name and overlay IPs with the existing private Pi CA.

## Automatic startup and preview follow-up

Executed on 2026-09-17 using camera release `boot-preview-c7acdfb0205f` and Web
release `b5c934e5e5c86b2b`. The installed camera service now uses `--auto-capture`;
both user services restart on failure without a systemd start-rate limit.

- Disabled the Mac camera-tunnel LaunchAgent, checked that no recording was
  active, and requested a normal Pi reboot. Closed SSH immediately afterwards.
- Polled certificate-validated `https://raspberrypi:8443` directly over Tailscale,
  without logging in again until HTTPS, sensor capture and synchronization were
  ready. Readiness took **37.95 seconds from the reboot request**. This is not a
  measurement from physical power-on.
- At readiness, capture reported `running: true`, no error, synchronization
  locked, sensor-pair p95 delta 19 microseconds and no active recording. The
  served HTML matched the deployed production build byte-for-byte.
- A subsequent SSH check confirmed a new kernel boot ID, unchanged calibration
  and recording-manifest hashes, enabled camera/Web/Tailscale services, and
  `Linger=yes`. Camera startup needed no retry; Web startup retried once while
  the Tailscale interface became available. Both services were active.
- After reboot, a 10-second diagnostic with both SDP directions restricted to
  Tailscale candidates decoded **194 H.264 frames** at 1440 × 540 and received
  **299 diagnostic messages**. PTS increased; synchronization remained locked
  with p95 delta 118 microseconds at sample end. The session was released and no
  recording was created. Restored the Mac tunnel after the standalone check.
- In the desktop in-app browser, `http://localhost:5173/?view=live` automatically
  connected to the real Pi stream and displayed **LIVE · Synced**, without
  pressing a preview button. Closing live preview returned to the sample editor
  without reopening the stream. This validates the automatic UI path, not
  physical iPad Safari autoplay or performance.
- Seven device API tests passed, including startup capture without recording,
  cleanup on startup failure and preservation of on-demand mode. TypeScript,
  the production build, 12 Web tests and 7 workbench-server tests passed.

The Pi now starts capture before a browser connects. Opening its HTTPS
workbench starts live preview automatically once the device and renderer are
ready; `?view=editor` opts out. An already-open browser's recovery across a Pi
reboot is separate from this first-visit startup result. Muted inline autoplay
is requested, but restrictive browser settings may still require a tap.

## Reproduce

On a development machine with `httpx` and `aiortc`, use the public CA certificate
from the Pi's setup page and its actual LAN address:

```sh
uv run --all-packages python tools/diagnostics/check-ipad.py \
  --url https://raspberrypi.local:8443 --ca /path/to/rpi360-ca.crt \
  --seconds 12 --output /path/to/result.json
```

For a Tailscale-only media check, use the short HTTPS address and add
`--tailscale-only`. The diagnostic rejects a client or Pi with no overlay ICE
candidate and excludes all LAN candidates from the offer and answer.

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
