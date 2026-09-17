# Live preview with only an iPad and a Pi

The Pi hosts the workbench, camera API and paired H.264 WebRTC stream. Safari
decodes the stream and renders the view on the iPad. FOV and orientation changes
stay on the iPad; no Mac, SSH tunnel or cloud service is needed at runtime.

This is a **trusted LAN** deployment: devices on the Pi's configured local subnet
can control the camera and download recordings. There are no pairing codes or
browser tokens. The gateway checks the peer subnet, hostname and browser origin;
the camera API itself stays on loopback. Use this on your private camera network.
Use the [token-protected HTTPS mode](camera.md#optional-direct-https-deployment)
instead when devices on the network must have separate access credentials.

## Install once on the Pi

Install a camera release using [the Pi setup](camera.md#1-on-the-pi), with your
rig's calibration. Stop its foreground `make camera` before the following step;
the installer refuses to interrupt a recording or an unmanaged camera process.

The Web build requires Node.js 22+, pnpm, Rust and wasm-bindgen-cli 0.2.108.
You can build on the Pi itself or copy `apps/web/dist` from another build machine;
the output is platform-independent and the Pi needs no Node/Rust at runtime.
From the repository root:

```sh
pnpm install --frozen-lockfile
rustup target add wasm32-unknown-unknown
cargo install wasm-bindgen-cli --version 0.2.108 --locked
pnpm wasm
pnpm build
make ipad CALIBRATION=/path/to/your/calibration.json
```

`make ipad` selects the active private LAN address, installs an isolated Caddy
binary from the Pi's configured Debian apt repository when necessary, creates
this Pi's local certificate authority and installs two user services. It asks
for sudo only if needed to enable services at boot, before an SSH login.
Close the terminal after it reports ready.

Recordings default to `~/.local/share/rpi360/data`. To keep using a different
existing recording directory, set `RPI360_DATA_DIR` before `make ipad`, or run:

```sh
python3 tools/install-ipad.py \
  --data-dir /path/to/existing/data \
  --calibration /path/to/your/calibration.json \
  --hostname raspberrypi.local --address 192.168.1.20/24
```

The address is an example; use the Pi's actual LAN address **and subnet prefix**.
Hostname discovery requires mDNS (normally provided by Raspberry Pi OS). The
printed IP address also works. Reserve the Pi's address in your router; rerun the
installer if its address or subnet changes. Existing recordings, calibration,
camera releases and the Mac preview launcher are preserved.

## First visit on the iPad

1. Connect the Pi and iPad to the same Wi-Fi/LAN, without guest/client isolation.
2. Open the **First iPad visit** URL printed by the installer, for example
   `http://raspberrypi.local:8080`. This setup page comes from the Pi.
3. Download the Pi certificate. In **Settings → General → VPN & Device
   Management**, select the downloaded RPI360 camera certificate and install it.
4. In **Settings → General → About → Certificate Trust Settings**, enable full
   trust for that certificate. This is required separately by
   [iPadOS](https://support.apple.com/102390).
5. Return to Safari and open `https://raspberrypi.local:8443`. Choose
   the **Open live preview** button at the top. Wait for **LIVE · Synced**.

The certificate trust step happens once per Pi/iPad. It enables Safari's secure
browser features; it is not a recurring pairing flow. The setup page shows the
public certificate fingerprint, also printed on the Pi. The CA private key stays
in the Pi's private application directory and is never served or copied to Git.
The HTTP setup port cannot access the API, workbench or recordings.

The preview button stays visible on phones, iPad portrait and Split View. The
**Camera** tab below it opens recording controls and the on-camera file list;
**Library** and **Effects** open their own panels. Close a panel with **Close**.

Drag to look around, use the Field of view slider to zoom, and select Source,
Panorama or Reframe. Bookmark the HTTPS address or add it to the Home Screen.
Keep the preview in the foreground; reopen it after a network interruption.
Only one live viewer is supported: close a Mac preview before opening the iPad.
Closing Safari does not stop a recording on the Pi.

## Connect over Tailscale

After installing the workbench, connect the Pi and iPad to the same tailnet and
turn on MagicDNS. On the Pi, from the repository root, run:

```sh
make tailscale
```

Open **https://raspberrypi:8443/** on the iPad, then **Open live preview**. Use your
Pi's actual Tailscale node name if it differs. The command also prints its
`https://100.x.y.z:8443/` fallback and adds both links to the certificate setup
page at `http://100.x.y.z:8080/`. A Mac, SSH tunnel, subnet router and exit node
are not required. The two devices can be on different physical networks.

This adds the Pi's short MagicDNS name and Tailscale IPs to
the gateway's certificates and origin checks, admits Tailscale overlay peers,
and enables its Tailscale IPv6 listener. The existing LAN addresses still work.
Only the Web service restarts; capture and recordings continue. Later `make ipad`
updates preserve this opt-in configuration. Rerun `make tailscale` if the Pi is
renamed or re-registered in Tailscale. Tailscale must run on the Pi at boot.

**Certificate trust:** the short name and IP use the same private Pi CA as the
LAN address. If that CA is already fully trusted on the iPad, nothing needs to
be reinstalled. Otherwise follow the first-visit steps using the Tailscale setup
URL. [Tailscale's public HTTPS certificates](https://tailscale.com/docs/how-to/set-up-https-certificates)
cover the full `.ts.net` name, not a bare name such as `raspberrypi`; this setup
uses Caddy's private CA deliberately so the requested short HTTPS address works.
The full `.ts.net` HTTPS URL is not configured by this private-CA mode.
Do not bypass a certificate warning.

The tailnet is a trusted camera network: reachable peers can operate the camera
and access recordings. RPI360 does not change Tailscale ACLs/grants, enable
Funnel or expose a public service. Use Tailscale access rules to restrict which
devices may reach the Pi. WebRTC also needs UDP connectivity to the Pi, beyond
TCP 8443 used by the workbench/API. Keep Tailscale's normal host firewall rules.

If the short name fails, check that MagicDNS and Tailscale DNS are enabled on the
iPad, then try the printed Tailscale IP. If the page opens but video does not,
close any other preview and check UDP access. To verify media with **only**
Tailscale ICE candidates (no silent LAN fallback), run the
[diagnostic](../validation/ipad-preview.md#reproduce) with `--tailscale-only`.

## Service management

```sh
systemctl --user status rpi360-camera rpi360-web
journalctl --user -u rpi360-camera -u rpi360-web -n 100
systemctl --user restart rpi360-web
# Finalize any recording before stopping the camera:
systemctl --user disable --now rpi360-web rpi360-camera
```

Both services restart after a crash. The workbench remains available if the
camera process is restarting. Static web releases and Caddy configuration live
under `~/.local/share/rpi360/lan`; camera data stays in its separate directory.
Rerun `make ipad` with the same data/calibration options to deploy a new Web
build. Failed readiness restores the previous configuration and service units.
Stopping services preserves all recordings and certificates. To remove trust
from an iPad, delete this Pi's certificate profile in Settings.

## Browser scope

Safari on iPadOS 26+ is the initial WebGPU target; Safari 26 introduced
[WebGPU](https://webkit.org/blog/17333/webkit-features-in-safari-26-0/).
The renderer also contains a WebGL2 backend, but older iPads are not certified.
Live video uses WebRTC; WebCodecs support for file editing/export is a separate
capability. The current renderer copies decoded pixels through a canvas before
GPU upload, so performance must be measured on each supported device.

The requested device is iPad Pro 11-inch (2nd generation), iPadOS 27.0.
Actual Safari video, GPU rendering, gestures, background/resume and sustained
latency still require that device's verification. A successful Pi gateway test
does not certify the iPad. See the [validation report](../validation/ipad-preview.md).
