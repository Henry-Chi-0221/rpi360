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


def render_config(template, *, base, release, host, interface):
    values = {
        "HOST": host,
        "IP": str(interface.ip),
        "SUBNET": str(interface.network),
        "STORAGE": json.dumps(str(base / "pki")),
        "WEB": json.dumps(str(release / "web")),
        "SETUP": json.dumps(str(base / "setup")),
    }
    for key, value in values.items():
        template = template.replace(f"@@{key}@@", value)
    return template


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
            template, base=lan, release=release, host=host, interface=interface
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
        ]
    )
    camera_text = f"""{MARKER}
[Unit]
Description=RPI360 camera capture and loopback API
After=network-online.target
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
        page = (ROOT / "deploy/raspberry-pi/ipad/index.html").read_text()
        for key, value in {
            "HOST": host,
            "IP": str(interface.ip),
            "FINGERPRINT": fingerprint,
        }.items():
            page = page.replace(f"@@{key}@@", value)
        atomic(lan / "setup/index.html", page)
        atomic(
            lan / "deployment.json",
            json.dumps(
                {
                    "host": host,
                    "address": str(interface),
                    "web_release": release.name,
                    "data_dir": str(data),
                    "ca_sha256": fingerprint,
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
    try:
        install(parser.parse_args())
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        raise SystemExit(f"iPad setup failed: {error}") from error
