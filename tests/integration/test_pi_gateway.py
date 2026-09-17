"""Exercise the real Caddy LAN gateway; no cameras or system services required."""

import contextlib
import http.client
import ipaddress
import json
import os
import runpy
import shutil
import socket
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CADDY = os.environ.get("RPI360_CADDY_BIN") or shutil.which("caddy")
pytestmark = pytest.mark.skipif(
    not CADDY, reason="Caddy is required for gateway integration"
)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def gateway(tmp_path_factory):
    base = tmp_path_factory.mktemp("gateway")
    (base / "web").mkdir()
    (base / "setup").mkdir()
    (base / "web/index.html").write_text("<h1>RPI360</h1>")
    (base / "web/render.wasm").write_bytes(b"0123456789")
    (base / "setup/index.html").write_text("Setup")
    received = []

    class Backend(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(dict(self.headers))
            self.send_response(206 if self.headers.get("Range") else 200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"path": self.path}).encode())

        do_POST = do_GET

        def log_message(self, *_):
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    https_port, http_port = free_port(), free_port()
    module = runpy.run_path(str(ROOT / "tools/install-ipad.py"))
    config = (
        module["render_config"](
            (ROOT / "deploy/raspberry-pi/ipad/Caddyfile.template").read_text(),
            base=base,
            release=base,
            host="camera.local",
            interface=ipaddress.ip_interface("127.0.0.1/8"),
        )
        .replace(":8443", f":{https_port}")
        .replace(":8080", f":{http_port}")
    )
    config = config.replace("127.0.0.1:8765", f"127.0.0.1:{backend.server_port}")
    # Two loopback source addresses exercise the real peer-subnet gate without
    # privileged network namespaces, Docker NAT or spoofable forwarded headers.
    config = config.replace("127.0.0.0/8", "127.0.0.1/32")
    (base / "Caddyfile").write_text(config)
    with (base / "caddy.log").open("w") as log:
        process = subprocess.Popen(
            [
                CADDY,
                "run",
                "--config",
                str(base / "Caddyfile"),
                "--adapter",
                "caddyfile",
            ],
            stdout=log,
            stderr=log,
        )
        try:
            ca = base / "pki/pki/authorities/local/root.crt"
            deadline = time.monotonic() + 15
            while not ca.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    pytest.fail((base / "caddy.log").read_text())
                time.sleep(0.1)
            context = ssl.create_default_context(cafile=str(ca))
            shutil.copyfile(ca, base / "setup/rpi360-ca.crt")
            url = f"https://127.0.0.1:{https_port}"
            module["wait_url"](url, context=context, timeout=10)

            def request(path, *, headers=None, method="GET", plain=False, source=None):
                if source:
                    connection = http.client.HTTPSConnection(
                        "127.0.0.1",
                        https_port,
                        context=context,
                        source_address=(source, 0),
                        timeout=5,
                    )
                    try:
                        connection.request(method, path, headers=headers or {})
                        response = connection.getresponse()
                        return response.status, response.headers, response.read()
                    finally:
                        connection.close()
                address = f"http://127.0.0.1:{http_port}" if plain else url
                req = urllib.request.Request(
                    address + path, headers=headers or {}, method=method
                )
                try:
                    with urllib.request.urlopen(req, context=context, timeout=5) as r:
                        return r.status, r.headers, r.read()
                except urllib.error.HTTPError as error:
                    return error.code, error.headers, error.read()

            yield request, received, url
        finally:
            process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)
            if process.poll() is None:
                process.kill()
                process.wait()
            backend.shutdown()
            backend.server_close()
            thread.join()


def test_https_assets_and_ranges(gateway):
    request, _, _ = gateway
    assert request("/")[0] == 200
    code, headers, body = request("/render.wasm", headers={"Range": "bytes=2-4"})
    assert code == 206 and body == b"234"
    assert headers["Content-Type"] == "application/wasm"


def test_setup_exposes_only_public_certificate_and_instructions(gateway):
    request, _, _ = gateway
    assert request("/", plain=True)[0] == 200
    assert b"BEGIN CERTIFICATE" in request("/rpi360-ca.crt", plain=True)[2]
    for path in ["/v1/info", "/api/v1/recordings", "/render.wasm", "/root.key"]:
        assert request(path, plain=True)[0] == 404
    assert request("/root.key")[0] == 404


def test_cross_site_controls_never_reach_camera(gateway):
    request, received, _ = gateway
    count = len(received)
    for headers in [
        {"Origin": "https://untrusted.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ]:
        assert request("/v1/capture/start", headers=headers, method="POST")[0] == 403
    assert len(received) == count
    assert request("/v1/info", headers={"Host": "untrusted.example"})[0] != 200


def test_same_origin_proxy_preserves_range_and_removes_forwarded_identity(gateway):
    request, received, url = gateway
    for prefix in ["", "/api"]:
        code, _, body = request(
            prefix + "/v1/recordings/a/files/camera0.mp4",
            headers={
                "Origin": url,
                "Range": "bytes=2-4",
                "X-Forwarded-For": "203.0.113.5",
                "Forwarded": "for=203.0.113.5",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        assert code == 206
        assert json.loads(body)["path"] == "/v1/recordings/a/files/camera0.mp4"
        headers = {k.lower(): v for k, v in received[-1].items()}
        assert headers["range"] == "bytes=2-4"
        assert headers["host"].startswith("127.0.0.1:")
        assert not any(
            k in headers
            for k in ["origin", "forwarded", "x-forwarded-for", "x-forwarded-proto"]
        )


def test_other_peer_subnet_cannot_spoof_a_local_forwarded_address(gateway):
    request, received, _ = gateway
    count = len(received)
    assert (
        request(
            "/v1/info",
            source="127.0.0.2",
            headers={
                "X-Forwarded-For": "127.0.0.1",
                "Forwarded": "for=127.0.0.1",
            },
        )[0]
        == 403
    )
    assert len(received) == count
