import json
from fractions import Fraction

import av
import numpy as np
from rpi360_camera.recording import BundleRecorder
from rpi360_camera.storage import RecordingStore
from rpi360_camera.synchronization import Pairer, SensorFrame


def test_sensor_pairing_relocks_after_discontinuity():
    p = Pairer(lock_ns=100_000_000)

    def send(t):
        p.push(SensorFrame(0, 0, t, 100, 33333, True))
        return p.push(SensorFrame(1, 0, t + 18_000, 100, 33333, True))

    assert send(1_000_000_000) is None
    assert send(1_100_000_000).delta_ns == 18_000
    assert send(500_000_000) is None
    assert not p.locked
    assert send(600_000_000) is not None


def test_mux_preserves_vfr_and_cross_camera_offset(tmp_path):
    recorder = BundleRecorder(
        RecordingStore(tmp_path), None, (64, 48), 30, 10_000_000_000, "test-boot"
    )
    expected = [
        [125_000, 158_333, 301_111, 502_000],
        [143_000, 176_333, 319_111, 520_000],
    ]
    for camera in (0, 1):
        encoder = av.CodecContext.create("libx264", "w")
        encoder.width, encoder.height = 64, 48
        encoder.pix_fmt = "yuv420p"
        encoder.time_base = Fraction(1, 1_000_000)
        encoder.options = {"preset": "ultrafast", "tune": "zerolatency"}
        for pts in expected[camera]:
            frame = av.VideoFrame.from_ndarray(
                np.full((48, 64, 3), 80 + camera * 60, np.uint8), format="rgb24"
            )
            frame.pts, frame.time_base = pts, encoder.time_base
            for packet in encoder.encode(frame):
                recorder.write(
                    camera,
                    bytes(packet),
                    10_000_000 + pts,
                    packet.is_keyframe,
                    {"sequence": pts},
                )
    result = recorder.close()
    assert result["state"] == "complete"
    for i in (0, 1):
        with av.open(str(recorder.path / f"camera{i}.mp4")) as media:
            pts = [
                round(f.pts * f.time_base * 1_000_000) for f in media.decode(video=0)
            ]
        offset = result["streams"][i]["media_start_offset_us"]
        assert [p + offset for p in pts] == expected[i]
        assert (
            len((recorder.path / f"camera{i}.frames.jsonl").read_text().splitlines())
            == 4
        )
    assert json.loads((recorder.path / "manifest.json").read_text())["files"]


def test_failed_recording_keeps_sources(tmp_path):
    recorder = BundleRecorder(
        RecordingStore(tmp_path), None, (64, 48), 30, 1000, "test"
    )
    recorder.write(0, b"invalid", 0, False, {})
    result = recorder.close()
    assert result["state"] == "recovery_required"
    assert (recorder.path / "camera0.mp4").exists()
