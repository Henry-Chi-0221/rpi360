from fastapi.testclient import TestClient
from rpi360_camera.api import create_app
from rpi360_camera.storage import RecordingStore, atomic_json, file_info


class Engine:
    def __init__(self, root):
        self.root = root
        self.store = RecordingStore(root / "recordings")
        self.calibration = None
        self.starts = 0
        self.stops = 0

    def start(self):
        pass

    def close(self):
        pass

    def status(self):
        return {"running": True, "sync": {"locked": True}}

    def start_recording(self):
        self.starts += 1
        return {"id": "a" * 32, "state": "recording"}

    def stop_recording(self):
        self.stops += 1
        return {"id": "a" * 32, "state": "complete"}


def local_client(app):
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000))


def test_local_access_idempotency_and_range_without_credentials(tmp_path):
    engine = Engine(tmp_path)
    app = create_app(engine)
    with local_client(app) as client:
        assert client.get("/v1/info").json()["access_mode"] == "local"
        assert client.get("/v1/capabilities").json()["control_policy"] == "shared"
        assert client.get("/v1/recordings").status_code == 200
        assert client.post("/v1/pair", json={"code": "000000"}).status_code == 404
        for _ in range(2):
            assert (
                client.post(
                    "/v1/recordings/start", json={"request_id": "retry-1234"}
                ).status_code
                == 200
            )
        assert engine.starts == 1
        path = engine.store.directory("a" * 32)
        path.mkdir()
        (path / "camera0.mp4").write_bytes(b"0123456789")
        atomic_json(
            path / "manifest.json",
            {
                "id": "a" * 32,
                "state": "complete",
                "files": [file_info(path / "camera0.mp4")],
            },
        )
        r = client.get(
            "/v1/recordings/" + "a" * 32 + "/files/camera0.mp4",
            headers={"Range": "bytes=3-6"},
        )
        assert r.status_code == 206 and r.content == b"3456"
        assert r.headers["content-range"] == "bytes 3-6/10"
        assert (
            client.get(
                "/v1/recordings/" + "a" * 32 + "/files/authorized-clients.json"
            ).status_code
            == 404
        )
        for _ in range(2):
            assert (
                client.post(
                    "/v1/recordings/stop", json={"request_id": "stop-1234"}
                ).status_code
                == 200
            )
        assert engine.stops == 1
        assert client.get("/v1/status").status_code == 200
        assert not (tmp_path / "authorized-clients.json").exists()
    # A second browser or SDK needs no saved credentials and can control the API.
    with local_client(create_app(engine)) as other:
        assert other.get("/v1/status").status_code == 200
        assert (
            other.post(
                "/v1/recordings/start", json={"request_id": "retry-1234"}
            ).status_code
            == 200
        )
        assert engine.starts == 1


def test_preview_answer_negotiates_h264_before_accepting_offer(tmp_path):
    import asyncio

    from aiortc import RTCConfiguration, RTCPeerConnection

    async def offer():
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        try:
            pc.addTransceiver("video", direction="recvonly")
            await pc.setLocalDescription(await pc.createOffer())
            return {"sdp": pc.localDescription.sdp, "type": "offer"}
        finally:
            await pc.close()

    body = asyncio.run(offer())
    assert "VP8/90000" in body["sdp"]
    engine = Engine(tmp_path)
    app = create_app(engine)
    with local_client(app) as client:
        r = client.post("/v1/preview-sessions", json=body)
        assert r.status_code == 200, r.text
        answer = r.json()["sdp"]
        assert "H264/90000" in answer
        assert "VP8/90000" not in answer
        assert client.post("/v1/preview-sessions", json=body).status_code == 409
        assert (
            client.delete("/v1/preview-sessions/" + r.json()["id"]).status_code == 200
        )


def test_local_access_rejects_remote_peer_rebinding_and_cross_site(tmp_path):
    app = create_app(Engine(tmp_path), ["http://localhost:5173"])
    with TestClient(
        app, base_url="http://localhost", client=("192.0.2.1", 50000)
    ) as remote:
        assert (
            remote.get(
                "/v1/status", headers={"X-Forwarded-For": "127.0.0.1"}
            ).status_code
            == 403
        )
    with local_client(app) as client:
        assert (
            client.get("/v1/status", headers={"Host": "attacker.example"}).status_code
            == 403
        )
        assert (
            client.post(
                "/v1/capture/start", headers={"Origin": "https://attacker.example"}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/v1/status", headers={"Sec-Fetch-Site": "cross-site"}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/v1/status", headers={"Origin": "http://localhost:5173"}
            ).status_code
            == 200
        )


def test_direct_deployment_requires_configured_bearer(tmp_path):
    token = "test-api-token-" * 3
    app = create_app(Engine(tmp_path), api_token=token)
    with TestClient(
        app, base_url="https://camera.local", client=("192.0.2.1", 50000)
    ) as client:
        assert client.get("/v1/info").json()["access_mode"] == "bearer"
        assert client.get("/v1/status").status_code == 401
        assert (
            client.get(
                "/v1/status", headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 401
        )
        client.headers["Authorization"] = "Bearer " + token
        assert client.get("/v1/status").status_code == 200
        assert (
            client.get(
                "/v1/status", headers={"Origin": "https://attacker.example"}
            ).status_code
            == 403
        )


def test_cli_refuses_unauthenticated_lan_before_starting_hardware(monkeypatch):
    import pytest
    from rpi360_camera.__main__ import main

    monkeypatch.setattr("sys.argv", ["rpi360-camera", "--host", "0.0.0.0"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
