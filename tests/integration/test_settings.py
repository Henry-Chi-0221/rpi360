import pytest
from rpi360_camera.capture import CaptureEngine
from rpi360_camera.settings import CameraSettings


def test_sensor_controls_use_revision_and_persist_only_success(tmp_path):
    engine = CaptureEngine(tmp_path)
    settings = CameraSettings(revision=1, auto_exposure=False, exposure_us=8000)
    result = engine.update_settings(settings)
    assert result["revision"] == 2
    assert CaptureEngine(tmp_path).settings.exposure_us == 8000
    with pytest.raises(ValueError, match="revision"):
        engine.update_settings(settings)
    assert engine.settings.exposure_us == 8000


def test_shutdown_releases_both_cameras_and_owner_after_driver_failure(tmp_path):
    engine = CaptureEngine(tmp_path)
    calls = []

    class Camera:
        def __init__(self, index):
            self.index = index

        def stop(self):
            calls.append((self.index, "stop"))
            if self.index == 0:
                raise RuntimeError("driver stopped responding")

        def close(self):
            calls.append((self.index, "close"))

    engine.cameras = [Camera(0), Camera(1)]
    engine.owner_lock = (tmp_path / "camera.lock").open("a")
    lock = engine.owner_lock
    with pytest.raises(ExceptionGroup):
        engine.close()
    assert calls == [(0, "stop"), (0, "close"), (1, "stop"), (1, "close")]
    assert lock.closed
    assert not engine.running
    engine.close()  # Repeated cleanup is harmless.
