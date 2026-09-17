"""Install a Pi-hosted HTTPS workbench and persistent camera, without a Mac runtime.

Uses Debian's authenticated Caddy package as an unprivileged, isolated binary.
Never installs a system-wide web server or a certificate on the invoking device.
"""

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "# Managed by RPI360 iPad setup"
PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(n) for n in ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
)


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def atomic(path, text):
    temp = path.with_name(path.name + ".new")
    temp.write_text(text)
    temp.replace(path)


def unit_arg(value):
    return json.dumps(str(value).replace("%", "%%").replace("$", "$$"))


def lan_address():
    rows = json.loads(subprocess.check_output(["ip", "-j", "-4", "addr", "show"]))
    candidates = []
    for row in rows:
        if row.get("operstate") != "UP" or row["ifname"].startswith(
            ("lo", "docker", "veth", "br-", "tailscale")
        ):
            continue
        for addr in row.get("addr_info", []):
            ip = ipaddress.ip_address(addr["local"])
            if any(ip in network for network in PRIVATE_NETWORKS):
                candidates.append(ipaddress.ip_interface(f"{ip}/{addr['prefixlen']}"))
    if not candidates:
        raise RuntimeError("Connect the Pi to a private Ethernet or Wi-Fi LAN first.")
    return candidates[0]


def get_caddy(base):
    existing = shutil.which("caddy")
    if existing:
        return Path(existing)
    binary = base / "tools/caddy"
    if not binary.exists():
        binary.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="rpi360-caddy-") as td:
            run("apt-get", "download", "caddy", cwd=td)
            packages = list(Path(td).glob("caddy_*.deb"))
            if len(packages) != 1:
                raise RuntimeError(
                    "Expected one Caddy package from configured apt repositories"
                )
            run("dpkg-deb", "-x", str(packages[0]), td + "/unpacked")
            shutil.copy2(Path(td) / "unpacked/usr/bin/caddy", binary)
            binary.chmod(0o700)
    return binary


TAILSCALE_NETWORKS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fd7a:115c:a1e0::/48"),
)


def tailscale_info(status=None):
    """Read only the current node identity; never change tailnet ACLs or DNS."""
    if status is None:
        status = json.loads(subprocess.check_output(["tailscale", "status", "--json"]))
    if status.get("BackendState") != "Running":
        raise RuntimeError(
            "Connect this Pi to Tailscale before running make tailscale."
        )
    node = status.get("Self", {})
    dns_name = node.get("DNSName", "").rstrip(".").lower()
    label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    if not re.fullmatch(rf"{label}(?:\.{label})+\.ts\.net", dns_name):
        raise RuntimeError("Tailscale did not report a valid node DNS name.")
    ips = [ipaddress.ip_address(value) for value in node.get("TailscaleIPs", [])]
    if (
        not ips
        or not any(ip.version == 4 for ip in ips)
        or any(
            not any(
                ip.version == net.version and ip in net for net in TAILSCALE_NETWORKS
            )
            for ip in ips
        )
    ):
        raise RuntimeError("Tailscale did not report valid overlay addresses.")
    if not status.get("CurrentTailnet", {}).get("MagicDNSEnabled"):
        raise RuntimeError(
            "Enable MagicDNS in your tailnet to use the short camera name."
        )
    return {"dns_name": dns_name, "ips": [str(ip) for ip in ips]}


def url_host(host):
    return f"[{host}]" if ":" in host else host


def render_config(template, *, base, release, host, interface, tailscale=None):
    hosts = [host, str(interface.ip)]
    peers = [str(interface.network), "127.0.0.0/8", "::1"]
    binds = ["0.0.0.0"]
    if tailscale:
        # Caddy delegates *.ts.net certificates to tailscaled even with tls
        # internal. This mode deliberately serves short names and overlay IPs
        # under the existing private CA, without requiring tailnet HTTPS setup.
        hosts += [tailscale["dns_name"].split(".")[0]]
        hosts += tailscale["ips"]
        peers += [str(net) for net in TAILSCALE_NETWORKS]
        binds += [url_host(ip) for ip in tailscale["ips"] if ":" in ip]
    hosts = list(dict.fromkeys(url_host(h) for h in hosts))
    values = {
        "HTTPS_SITES": ", ".join(f"https://{h}:8443" for h in hosts),
        "HTTP_SITES": ", ".join(f"http://{h}:8080" for h in hosts),
        "ORIGINS": "\n".join(f"\t\t\t\theader Origin https://{h}:8443" for h in hosts),
        "PEER_NETWORKS": " ".join(peers),
        "BIND_HOSTS": " ".join(binds),
        "STORAGE": json.dumps(str(base / "pki")),
        "WEB": json.dumps(str(release / "web")),
        "SETUP": json.dumps(str(base / "setup")),
    }
    for key, value in values.items():
        template = template.replace(f"@@{key}@@", value)
    return template


def setup_page(host, ip, fingerprint, tailscale=None):
    page = (ROOT / "deploy/raspberry-pi/ipad/index.html").read_text()
    links = ""
    if tailscale:
        name = tailscale["dns_name"].split(".")[0]
        address = next(ip for ip in tailscale["ips"] if ":" not in ip)
        links = (
            "<h2>Over Tailscale</h2><p>Connect this iPad and Pi to your tailnet. "
            "The same Pi certificate works on both networks.</p>"
            f'<p><a class="button" href="https://{name}:8443/">'
            f"Open {name} over Tailscale</a></p>"
            f'<p>IP fallback: <a href="https://{address}:8443/">{address}</a>.</p>'
        )
    for key, value in {
        "HOST": host,
        "IP": ip,
        "FINGERPRINT": fingerprint,
        "TAILSCALE_LINKS": links,
    }.items():
        page = page.replace(f"@@{key}@@", value)
    return page


def configure_tailscale():
    """Add the overlay to an installed gateway; leave capture and data untouched."""
    lan = Path.home() / ".local/share/rpi360/lan"
    metadata = lan / "deployment.json"
    if not metadata.is_file():
        raise RuntimeError("Install the Pi workbench with make ipad first.")
    unit = Path.home() / ".config/systemd/user/rpi360-web.service"
    if not unit.exists() or MARKER not in unit.read_text():
        raise RuntimeError("The existing Web service is not managed by RPI360.")
    data = json.loads(metadata.read_text())
    overlay = tailscale_info()
    config = lan / "Caddyfile"
    setup = lan / "setup/index.html"
    previous = {p: p.read_text() for p in [config, setup, metadata]}
    candidate = lan / "Caddyfile.candidate"
    candidate.write_text(
        render_config(
            (ROOT / "deploy/raspberry-pi/ipad/Caddyfile.template").read_text(),
            base=lan,
            release=lan / "releases" / data["web_release"],
            host=data["host"],
            interface=ipaddress.ip_interface(data["address"]),
            tailscale=overlay,
        )
    )
    binary = get_caddy(lan)
    run(str(binary), "validate", "--config", str(candidate), "--adapter", "caddyfile")
    ca = lan / "setup/rpi360-ca.crt"
    context = ssl.create_default_context(cafile=str(ca))
    address = next(ip for ip in overlay["ips"] if ":" not in ip)
    try:
        atomic(config, candidate.read_text())
        run("systemctl", "--user", "restart", "rpi360-web")
        wait_url(f"https://{address}:8443/", context=context)
        wait_url(f"https://{address}:8443/v1/capabilities", context=context)
        data["tailscale"] = overlay
        atomic(
            setup,
            setup_page(
                data["host"], data["address"].split("/")[0], data["ca_sha256"], overlay
            ),
        )
        atomic(metadata, json.dumps(data, indent=2) + "\n")
    except Exception:
        for path, content in previous.items():
            atomic(path, content)
        run("systemctl", "--user", "restart", "rpi360-web")
        raise
    name = overlay["dns_name"].split(".")[0]
    print(f"Tailscale preview ready: https://{name}:8443/")
    print(f"IP fallback: https://{address}:8443/")
    print(f"First iPad visit: http://{address}:8080/")
    print("Uses the same Pi CA. Camera process, recordings and tailnet ACLs unchanged.")


def wait_url(url, *, context=None, timeout=45):
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(url, context=context, timeout=3) as response:
                return response.read()
        except (OSError, urllib.error.URLError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)


def install(args):
    if os.geteuid() == 0:
        raise RuntimeError(
            "Run as the camera user, not root. Only login startup uses sudo."
        )
    interface = ipaddress.ip_interface(args.address) if args.address else lan_address()
    if interface.version != 4 or not any(
        interface.network.subnet_of(n) for n in PRIVATE_NETWORKS
    ):
        raise RuntimeError("Use a private LAN IPv4 address with its subnet prefix.")
    host = args.hostname or socket.gethostname().split(".")[0] + ".local"
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,62}\.local", host):
        raise RuntimeError("Use a simple camera hostname ending in .local")
    home = Path.home()
    base = home / ".local/share/rpi360"
    lan = base / "lan"
    metadata = lan / "deployment.json"
    old_deployment = json.loads(metadata.read_text()) if metadata.is_file() else {}
    overlay = tailscale_info() if old_deployment.get("tailscale") else None
    data = Path(
        args.data_dir or os.environ.get("RPI360_DATA_DIR", base / "data")
    ).resolve()
    calibration = Path(args.calibration or data / "calibration.json").resolve()
    web = Path(args.web_root).resolve()
    executable = base / "current/.venv/bin/rpi360-camera"
    if not executable.is_file() or not calibration.is_file():
        raise RuntimeError(
            "Install the camera release and provide --calibration first."
        )
    help_text = subprocess.check_output([str(executable), "--help"], text=True)
    if "--auto-capture" not in help_text:
        raise RuntimeError(
            "Install a current camera release with --auto-capture support first."
        )
    if not (web / "index.html").is_file() or not list(web.rglob("*.wasm")):
        raise RuntimeError("Build the workbench first: pnpm wasm && pnpm build")
    # A foreground capture must be stopped deliberately, never killed by port number.
    managed = subprocess.run(
        ["systemctl", "--user", "is-active", "--quiet", "rpi360-camera"]
    )
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/v1/status", timeout=2) as r:
            status = json.load(r)
        if status.get("recording"):
            raise RuntimeError("Stop/finalize the active recording before installing.")
        if managed.returncode:
            raise RuntimeError(
                "Stop the foreground camera service, then rerun make ipad."
            )
    except (OSError, urllib.error.URLError):
        pass
    for directory in [lan / "releases", lan / "pki", lan / "setup", data]:
        directory.mkdir(parents=True, exist_ok=True)
    lan.chmod(0o700)
    binary = get_caddy(lan)
    digest = hashlib.sha256()
    entries = list(web.rglob("*"))
    if any(p.is_symlink() for p in entries):
        raise RuntimeError("Web release must not contain symlinks")
    files = sorted(p for p in entries if p.is_file())
    for file in files:
        digest.update(str(file.relative_to(web)).encode() + b"\0" + file.read_bytes())
    release = lan / "releases" / digest.hexdigest()[:16]
    if not release.exists():
        with tempfile.TemporaryDirectory(dir=lan / "releases") as stage:
            staging = Path(stage) / "release"
            shutil.copytree(web, staging / "web")
            staging.rename(release)
    template = (ROOT / "deploy/raspberry-pi/ipad/Caddyfile.template").read_text()
    candidate = lan / "Caddyfile.candidate"
    candidate.write_text(
        render_config(
            template,
            base=lan,
            release=release,
            host=host,
            interface=interface,
            tailscale=overlay,
        )
    )
    run(str(binary), "validate", "--config", str(candidate), "--adapter", "caddyfile")
    units = home / ".config/systemd/user"
    units.mkdir(parents=True, exist_ok=True)
    camera_unit = units / "rpi360-camera.service"
    web_unit = units / "rpi360-web.service"
    for unit in [camera_unit, web_unit]:
        if unit.exists() and MARKER not in unit.read_text():
            raise RuntimeError(
                f"Existing unit is not managed by this installer: {unit}"
            )
    camera_command = " ".join(
        unit_arg(value)
        for value in [
            executable,
            "--data-dir",
            data,
            "--calibration",
            calibration,
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--auto-capture",
        ]
    )
    camera_text = f"""{MARKER}
[Unit]
Description=RPI360 camera capture and loopback API
After=network-online.target
StartLimitIntervalSec=0
[Service]
ExecStart={camera_command}
Restart=always
RestartSec=3
TimeoutStopSec=120
UMask=0077
NoNewPrivileges=true
[Install]
WantedBy=default.target
"""
    web_command = " ".join(
        unit_arg(value)
        for value in [
            binary,
            "run",
            "--config",
            lan / "Caddyfile",
            "--adapter",
            "caddyfile",
        ]
    )
    web_text = f"""{MARKER}
[Unit]
Description=RPI360 Pi HTTPS workbench
After=network-online.target
StartLimitIntervalSec=0
[Service]
ExecStart={web_command}
Restart=always
RestartSec=3
UMask=0077
NoNewPrivileges=true
[Install]
WantedBy=default.target
"""
    config = lan / "Caddyfile"
    previous = {
        p: p.read_text() if p.exists() else None
        for p in [config, camera_unit, web_unit]
    }
    try:
        atomic(config, candidate.read_text())
        atomic(camera_unit, camera_text)
        atomic(web_unit, web_text)
        run("systemctl", "--user", "daemon-reload")
        run("systemctl", "--user", "enable", "rpi360-camera", "rpi360-web")
        run("systemctl", "--user", "restart", "rpi360-camera", "rpi360-web")
        wait_url("http://127.0.0.1:8765/v1/info")
        ca = lan / "pki/pki/authorities/local/root.crt"
        deadline = time.monotonic() + 30
        while not ca.exists():
            if time.monotonic() > deadline:
                raise RuntimeError("Pi HTTPS certificate was not generated")
            time.sleep(0.5)
        context = ssl.create_default_context(cafile=str(ca))
        wait_url(f"https://{interface.ip}:8443/", context=context)
        wait_url(f"https://{interface.ip}:8443/v1/capabilities", context=context)
        shutil.copyfile(ca, lan / "setup/rpi360-ca.crt")
        fingerprint = (
            hashlib.sha256(ssl.PEM_cert_to_DER_cert(ca.read_text())).hexdigest().upper()
        )
        fingerprint = ":".join(
            fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2)
        )
        atomic(
            lan / "setup/index.html",
            setup_page(host, str(interface.ip), fingerprint, overlay),
        )
        atomic(
            lan / "deployment.json",
            json.dumps(
                {
                    "host": host,
                    "address": str(interface),
                    "web_release": release.name,
                    "data_dir": str(data),
                    "ca_sha256": fingerprint,
                    "tailscale": overlay,
                },
                indent=2,
            )
            + "\n",
        )
    except Exception:
        subprocess.run(["systemctl", "--user", "stop", "rpi360-web", "rpi360-camera"])
        for unit in [camera_unit, web_unit]:
            if previous[unit] is None:
                subprocess.run(["systemctl", "--user", "disable", unit.name])
        for path, content in previous.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic(path, content)
        run("systemctl", "--user", "daemon-reload")
        for unit in [camera_unit, web_unit]:
            if previous[unit] is not None:
                run("systemctl", "--user", "start", unit.name)
        raise
    # Lingering keeps the user services alive after SSH logout and starts at boot.
    linger = subprocess.check_output(
        ["loginctl", "show-user", str(os.getuid()), "-p", "Linger", "--value"],
        text=True,
    ).strip()
    if linger != "yes":
        run("sudo", "loginctl", "enable-linger", str(os.getuid()))
    print(
        f"\nPi workbench ready: https://{host}:8443/ (or https://{interface.ip}:8443/)"
    )
    print(f"First iPad visit: http://{interface.ip}:8080/")
    print(f"Certificate SHA-256: {fingerprint}")
    print("No Mac or SSH session is needed at runtime. Both services start at Pi boot.")
    print(
        "Trusted LAN mode: devices on this subnet can control the camera "
        "and download recordings."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-root", default=str(ROOT / "apps/web/dist"))
    parser.add_argument("--data-dir")
    parser.add_argument("--calibration")
    parser.add_argument("--hostname")
    parser.add_argument(
        "--address", help="Private LAN IPv4/prefix, e.g. 192.168.1.20/24"
    )
    parser.add_argument(
        "--configure-tailscale",
        action="store_true",
        help="Add Tailscale to an existing gateway without restarting capture",
    )
    try:
        args = parser.parse_args()
        if args.configure_tailscale:
            configure_tailscale()
        else:
            install(args)
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        raise SystemExit(f"iPad setup failed: {error}") from error
