import hashlib
import json
from fractions import Fraction

import av
import numpy as np
import pytest
from rpi360_camera.recording import BundleRecorder
from rpi360_camera.recovery import recover
from rpi360_camera.storage import RecordingStore


def recording(root):
    recorder = BundleRecorder(RecordingStore(root), None, (64, 48), 10, 0, "test")
    for camera in (0, 1):
        encoder = av.CodecContext.create("libx264", "w")
        encoder.width, encoder.height = 64, 48
        encoder.pix_fmt = "yuv420p"
        encoder.time_base = Fraction(1, 1_000_000)
        encoder.gop_size = 10
        encoder.options = {"preset": "ultrafast", "tune": "zerolatency"}
        for n in range(35):
            frame = av.VideoFrame.from_ndarray(
                np.full((48, 64, 3), n, np.uint8), format="rgb24"
            )
            frame.pts, frame.time_base = n * 100_000 + camera * 18, encoder.time_base
            for p in encoder.encode(frame):
                recorder.write(camera, bytes(p), frame.pts, p.is_keyframe, {})
    recorder.close()
    return recorder


def test_torn_fragment_recovers_committed_frames_without_touching_source(tmp_path):
    r = recording(tmp_path / "recordings")
    for camera in (0, 1):
        path = r.path / f"camera{camera}.mp4"
        data = path.read_bytes()
        # Cut through the final mdat, not merely the optional mfra footer.
        pos = data.rfind(b"mdat")
        path.write_bytes(data[: pos + 5])
        with (r.path / f"camera{camera}.frames.jsonl").open("a") as f:
            f.write('{"unfinished":')
    before = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in r.path.iterdir()
    }
    dest = tmp_path / "recovered.r360"
    result = recover(r.path, dest)
    assert result["state"] == "recovered"
    assert result["recovered_from"] == r.id
    assert before == {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in r.path.iterdir()
    }
    for stream in result["streams"]:
        with av.open(str(dest / stream["path"])) as video:
            frames = list(video.decode(video=0))
        assert 20 <= len(frames) < 35
        rows = [
            json.loads(line)
            for line in (dest / f"camera{stream['camera']}.frames.jsonl")
            .read_text()
            .splitlines()
        ]
        assert len(rows) == len(frames) == stream["metadata_frames"]
        assert [round(f.pts * f.time_base * 1e6) for f in frames] == [
            r["media_pts_us"] for r in rows
        ]
    with pytest.raises(FileExistsError):
        recover(r.path, dest)


def test_hash_failure_is_recoverable_and_handles_are_closed(tmp_path, monkeypatch):
    r = recording(tmp_path)
    # Exercise finalize independently from earlier successful file hashes.
    r.closed = False
    import rpi360_camera.recording as module

    def fail(_):
        raise OSError("simulated checksum read failure")

    monkeypatch.setattr(module, "file_info", fail)
    assert r.close()["state"] == "recovery_required"
    assert all(f.closed for f in r.handles + r.indices)
    assert (r.path / "camera0.mp4").stat().st_size > 0
