import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
from rpi360 import FrameBundle, FrameOutput, Player, PlayerState, View

from tests.helpers import make_dual_track_recording, sample_calibration

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class FrameBundleTests(unittest.TestCase):
    def test_lazy_readonly_stages_and_projection_cache(self):
        source = np.full((64, 64, 3), (255, 20, 10), dtype=np.uint8)
        frame = FrameBundle(
            source,
            np.full((64, 64, 3), (5, 30, 240), dtype=np.uint8),
            sample_calibration(),
            index=7,
            timestamp0=1.0,
            timestamp1=1.001,
            panorama_size=(128, 64),
        )
        source[:] = 0
        self.assertFalse(frame.camera0.flags.writeable)
        self.assertEqual(frame.sync_error_us, 1000)
        view = View("perspective", size=(64, 32), fov=90)
        self.assertEqual(frame.render(view).shape, (32, 64, 3))
        view.configure("stereographic", size=(64, 64), fov=150)
        self.assertEqual(frame.render(view).shape, (64, 64, 3))
        self.assertEqual(frame.stitch_count, 1)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe are required")
class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "recording.r360.mp4"
        make_dual_track_recording(self.path, reverse_camera_mapping=True)

    def tearDown(self):
        self.temporary.cleanup()

    def test_mp4_outputs_all_readonly_bgr_stages(self):
        with Player.mp4(
            self.path,
            size=(64, 32),
            panorama_size=(128, 64),
            paced=False,
        ) as player:
            frame = player.next(timeout=None)
            self.assertIsNotNone(frame)
            for image in (
                frame.camera0,
                frame.camera1,
                frame.equi_1,
                frame.equi_2,
                frame.equi_blended,
                frame.image,
            ):
                self.assertEqual(image.dtype, np.uint8)
                self.assertEqual(image.shape[2], 3)
                self.assertFalse(image.flags.writeable)
            self.assertGreater(
                int(frame.camera0[10, 10, 0]),
                int(frame.camera0[10, 10, 2]),
            )
            self.assertGreater(
                int(frame.camera1[10, 10, 2]),
                int(frame.camera1[10, 10, 0]),
            )
            self.assertIs(frame.output(), frame.image)
            self.assertIs(frame.output(FrameOutput.CAMERA0), frame.camera0)
            self.assertIs(frame.output("equi_blended"), frame.equi_blended)
            with self.assertRaisesRegex(ValueError, "output must be one of"):
                frame.output("unknown")

    def test_view_change_redraws_same_bundle_without_restitch(self):
        with Player.mp4(
            self.path,
            size=(64, 32),
            panorama_size=(128, 64),
            paced=False,
        ) as player:
            first = player.next(timeout=None)
            player.rotate(yaw=10)
            second = player.next(timeout=0)
            self.assertIs(first.bundle, second.bundle)
            self.assertEqual(second.bundle.stitch_count, 1)
            self.assertFalse(
                np.array_equal(first.view.rotation_matrix, second.view.rotation_matrix)
            )

    def test_absolute_orientation_redraws_without_accumulating(self):
        with Player.mp4(
            self.path,
            size=(64, 32),
            panorama_size=(128, 64),
            paced=False,
        ) as player:
            first = player.next(timeout=None)
            player.set_orientation(yaw=20, pitch=-90, roll=45)
            second = player.next(timeout=0)
            player.set_orientation(yaw=20, pitch=-90, roll=45)
            third = player.next(timeout=0)
            np.testing.assert_allclose(
                second.view.rotation_matrix,
                third.view.rotation_matrix,
            )
            self.assertIs(first.bundle, second.bundle)
            self.assertIs(second.bundle, third.bundle)

    def test_pause_seek_step_restart_and_eos(self):
        with Player.mp4(self.path, paced=False) as player:
            first = player.next(timeout=None)
            player.pause()
            self.assertIsNone(player.next(timeout=0))
            stepped = player.step(1)
            self.assertEqual(stepped.frame_index, first.frame_index + 1)
            player.seek(0.59)
            sought = player.next(timeout=None)
            self.assertAlmostEqual(sought.timestamp, 0.6)
            player.restart()
            self.assertAlmostEqual(player.next(timeout=None).timestamp, 0.0)
            player.play()
            while player.next(timeout=None) is not None:
                pass
            self.assertEqual(player.state, PlayerState.ENDED)


if __name__ == "__main__":
    unittest.main()
