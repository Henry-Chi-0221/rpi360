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


def test_auth_origin_idempotency_revocation_and_range(tmp_path):
    engine = Engine(tmp_path)
    app = create_app(engine)
    with TestClient(app) as client:
        assert client.get("/v1/recordings").status_code == 401
        assert (
            client.post(
                "/v1/pair",
                json={"code": "000000", "name": "test"},
                headers={"Origin": "https://attacker.example"},
            ).status_code
            == 403
        )
        r = client.post("/v1/pair", json={"code": app.state.auth.code, "name": "test"})
        assert r.status_code == 200
        client.headers["Authorization"] = "Bearer " + r.json()["token"]
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
        assert client.delete("/v1/pair").status_code == 200
        assert client.get("/v1/status").status_code == 401


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
    with TestClient(app) as client:
        token = client.post(
            "/v1/pair", json={"code": app.state.auth.code, "name": "codec test"}
        ).json()["token"]
        client.headers["Authorization"] = "Bearer " + token
        r = client.post("/v1/preview-sessions", json=body)
        assert r.status_code == 200, r.text
        answer = r.json()["sdp"]
        assert "H264/90000" in answer
        assert "VP8/90000" not in answer
        assert client.post("/v1/preview-sessions", json=body).status_code == 409
        assert (
            client.delete("/v1/preview-sessions/" + r.json()["id"]).status_code == 200
        )
