import shutil
import tempfile
import unittest
from pathlib import Path

from rpi360.playback.mp4 import DualTrackReader, RPI360Recording

from tests.helpers import make_dual_track_recording

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe are required")
class MediaTests(unittest.TestCase):
    def test_timeline_and_native_pairing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recording.r360.mp4"
            make_dual_track_recording(path)
            recording = RPI360Recording.open(path)
            self.assertEqual(len(recording.timeline["camera_0"]), 5)
            with DualTrackReader(recording) as reader:
                pairs = []
                while True:
                    pair = reader.read()
                    if pair is None:
                        break
                    pairs.append(pair)
            self.assertEqual(len(pairs), 5)
            for _, _, timestamp0, timestamp1 in pairs:
                self.assertAlmostEqual(timestamp0, timestamp1)


if __name__ == "__main__":
    unittest.main()
