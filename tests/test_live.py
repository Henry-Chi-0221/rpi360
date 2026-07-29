import shutil
import sys
import tempfile
import time
import types
import unittest
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
from unittest import mock

import numpy as np

from rpi360 import CaptureError, Player, UnsupportedOperationError
from rpi360.common.metadata import (
    calibration_result_from_profile,
    read_embedded_calibration_result,
    save_calibration_result,
)
from rpi360.rpi.camera import CameraDevice
from tests.helpers import make_dual_track_recording, sample_calibration

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class FakePicamera2:
    def __init__(self, camera_num):
        self.camera_num = camera_num
        self.sensor_modes = [
            {"size": (1920, 1080)},
            {"size": (3280, 2464)},
        ]
        self.frame_number = 0
        self.encoder = None

    def create_preview_configuration(self, **values):
        return values

    def create_video_configuration(self, **values):
        return values

    def configure(self, configuration):
        self.configuration = configuration

    def start(self):
        pass

    def capture_array(self, _stream):
        time.sleep(0.005)
        self.frame_number += 1
        color = (0, 0, 220) if self.camera_num == 10 else (220, 0, 0)
        return np.full((64, 64, 3), color, dtype=np.uint8)

    def start_encoder(self, encoder, output, **_kwargs):
        self.encoder = encoder
        Path(output.path).touch()

    def stop_encoder(self, *_args):
        self.encoder = None

    def stop(self):
        pass

    def close(self):
        pass


class ReplayingPicamera2(FakePicamera2):
    frames = {}

    def capture_array(self, _stream):
        time.sleep(0.005)
        self.frame_number += 1
        return self.frames[self.camera_num].copy()


class LibavH264Encoder:
    def __init__(self, **values):
        self.values = values
        self.preset = None
        self.threads = 0


class FileOutput:
    def __init__(self, path):
        self.path = path


@contextmanager
def fake_picamera_encoder_modules():
    parent = types.ModuleType("picamera2")
    parent.__path__ = []
    encoders = types.ModuleType("picamera2.encoders")
    encoders.H264Encoder = LibavH264Encoder
    outputs = types.ModuleType("picamera2.outputs")
    outputs.FileOutput = FileOutput
    with mock.patch.dict(
        sys.modules,
        {
            "picamera2": parent,
            "picamera2.encoders": encoders,
            "picamera2.outputs": outputs,
        },
    ):
        yield


class LivePlayerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.calibration = Path(self.temporary.name) / "calibration.json"
        save_calibration_result(
            self.calibration,
            calibration_result_from_profile(sample_calibration(), {"fixture": True}),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def player(self):
        return Player.live(
            self.calibration,
            camera_indices=(10, 11),
            preview_size=(64, 64),
            fps=10,
            size=(64, 32),
            panorama_size=(128, 64),
            camera_factory=FakePicamera2,
        )

    def test_live_pause_keeps_capture_latest_and_view_redraws(self):
        with self.player() as player:
            first = player.next(timeout=1)
            player.pause()
            time.sleep(0.05)
            player.rotate(yaw=5)
            redrawn = player.next(timeout=0)
            self.assertIs(redrawn.bundle, first.bundle)
            player.play()
            latest = player.next(timeout=1)
            self.assertGreater(latest.frame_index, first.frame_index)
            with self.assertRaises(UnsupportedOperationError):
                player.seek(0)

    def test_live_inspect_exposes_shared_bgr_processing_contract(self):
        with self.player() as player:
            details = player.inspect()
            self.assertEqual(details["source"], "live")
            self.assertEqual(details["camera_indices"], [10, 11])
            self.assertEqual(details["processing_sizes"], [[64, 64], [64, 64]])
            self.assertEqual(details["pixel_format"], "bgr24")
            self.assertEqual(details["panorama_size"], [128, 64])

    def test_recording_uses_picamera_h264_and_is_idempotent(self):
        output = Path(self.temporary.name) / "capture.r360.mp4"

        def fake_mux(_tracks, output_path, **kwargs):
            self.assertTrue(kwargs["calibration_result"]["diagnostics"]["fixture"])
            Path(output_path).touch()
            return Path(output_path)

        with (
            fake_picamera_encoder_modules(),
            mock.patch("rpi360.rpi.live.mux_recording", side_effect=fake_mux),
        ):
            with self.player() as player:
                handle = player.start_recording(output)
                time.sleep(0.06)
                self.assertEqual(
                    player._source.devices[0].encoder_name,
                    "LibavH264Encoder",
                )
                self.assertEqual(handle.stop(), output)
                self.assertEqual(handle.stop(), output)

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe are required")
    def test_same_bgr_pair_is_pixel_exact_through_mp4_and_live_players(self):
        recording = Path(self.temporary.name) / "reference.r360.mp4"
        make_dual_track_recording(recording, reverse_camera_mapping=True)
        save_calibration_result(
            self.calibration,
            read_embedded_calibration_result(recording),
            overwrite=True,
        )
        player_options = {
            "projection": "stereographic",
            "size": (64, 32),
            "fov": 150.0,
            "quality": "fast",
            "panorama_size": (128, 64),
        }
        with Player.mp4(recording, paced=False, **player_options) as recorded:
            mp4_frame = recorded.next(timeout=None)

        ReplayingPicamera2.frames = {
            10: mp4_frame.camera0,
            11: mp4_frame.camera1,
        }
        with Player.live(
            self.calibration,
            camera_indices=(10, 11),
            preview_size=(64, 64),
            fps=10,
            camera_factory=ReplayingPicamera2,
            **player_options,
        ) as live:
            live_frame = live.next(timeout=1)

        for name in (
            "camera0",
            "camera1",
            "equi_1",
            "equi_2",
            "equi_blended",
            "image",
        ):
            self.assertTrue(
                np.array_equal(getattr(mp4_frame, name), getattr(live_frame, name)),
                name,
            )


class CameraBackendTests(unittest.TestCase):
    def test_missing_picamera2_raises_without_fallback(self):
        with mock.patch.dict(sys.modules, {"picamera2": None}):
            with self.assertRaisesRegex(CaptureError, "Picamera2 is required"):
                CameraDevice(0, preview_size=(64, 64)).start()

    def test_default_selects_largest_even_sensor_mode(self):
        camera = CameraDevice(
            0,
            preview_size=(640, 480),
            camera_factory=FakePicamera2,
        ).start()
        try:
            self.assertEqual(camera.record_size, (3280, 2464))
        finally:
            camera.stop()

    def test_read_rejects_unexpected_processing_size(self):
        camera = CameraDevice(
            0,
            preview_size=(32, 24),
            record_size=(64, 64),
            camera_factory=FakePicamera2,
        ).start()
        try:
            with self.assertRaisesRegex(CaptureError, "returned shape"):
                camera.read()
        finally:
            camera.stop()

    def test_explicit_odd_h264_size_fails_immediately(self):
        with self.assertRaisesRegex(ValueError, "must be even"):
            CameraDevice(
                0,
                preview_size=(640, 480),
                record_size=(1279, 720),
                camera_factory=FakePicamera2,
            )

    def test_pi5_alias_uses_ultrafast_libav_encoder(self):
        camera = CameraDevice(
            0,
            preview_size=(640, 480),
            record_size=(1280, 720),
            fps=30,
            camera_factory=FakePicamera2,
        ).start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "track.h264"
                with fake_picamera_encoder_modules():
                    camera.start_recording(output)
                    self.assertEqual(camera.encoder_name, "LibavH264Encoder")
                    self.assertEqual(camera._encoder.preset, "ultrafast")
                    self.assertEqual(camera._encoder.threads, 1)
                    self.assertEqual(
                        camera._encoder.values["framerate"],
                        Fraction(30, 1),
                    )
                    camera.stop_recording()
        finally:
            camera.stop()


if __name__ == "__main__":
    unittest.main()
