import pytest

from rpi360.client import DeviceClient


def test_recording_waits_for_real_sync_lock(monkeypatch):
    client = DeviceClient("http://camera")
    states = iter(
        [
            {"running": True, "sync": {"locked": False}},
            {"running": True, "sync": {"locked": True}},
        ]
    )
    monkeypatch.setattr(client, "status", lambda: next(states))
    monkeypatch.setattr("rpi360.client.time.sleep", lambda _: None)
    assert client.wait_for_sync()["sync"]["locked"]


def test_sync_wait_surfaces_capture_failure_and_timeout(monkeypatch):
    client = DeviceClient("http://camera")
    monkeypatch.setattr(client, "status", lambda: {"error": "sensor disconnected"})
    with pytest.raises(RuntimeError, match="sensor disconnected"):
        client.wait_for_sync()
    monkeypatch.setattr(client, "status", lambda: {"running": False})
    with pytest.raises(RuntimeError, match="start_capture"):
        client.wait_for_sync()
    monkeypatch.setattr(client, "status", lambda: {"running": True, "sync": {}})
    clock = iter([0, 16])
    monkeypatch.setattr("rpi360.client.time.monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError):
        client.wait_for_sync(timeout=15)
