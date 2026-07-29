import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from rpi360 import MetadataError
from rpi360.common.metadata import (
    calibration_from_metadata,
    find_camera_tracks,
    read_r360_metadata,
    write_r360_metadata,
)
from rpi360.common.types import validate_rotation_matrix
from rpi360.playback.mp4 import RPI360Recording
from tests.helpers import make_dual_track_recording

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class CommonTests(unittest.TestCase):
    def test_rejects_reflection_as_rotation(self):
        with self.assertRaisesRegex(ValueError, "determinant"):
            validate_rotation_matrix(np.diag([1.0, 1.0, -1.0]))

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe are required")
    def test_metadata_round_trip_and_track_mapping_uses_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recording.r360.mp4"
            expected = make_dual_track_recording(path, reverse_camera_mapping=True)
            metadata = read_r360_metadata(path)
            tracks = find_camera_tracks(path)
            # camera_0 intentionally points at the second physical MP4 stream.
            self.assertEqual(tracks["camera_0"]["index"], 1)
            self.assertEqual(tracks["camera_1"]["index"], 0)
            restored = calibration_from_metadata(metadata)
            np.testing.assert_allclose(restored.camera0.K, expected.camera0.K)
            np.testing.assert_allclose(restored.R_cam1_to_cam0, expected.R_cam1_to_cam0)

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe are required")
    def test_missing_metadata_has_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ordinary.mp4"
            import subprocess

            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=s=32x32:d=0.2",
                    str(path),
                ],
                check=True,
            )
            with self.assertRaisesRegex(MetadataError, "does not contain"):
                read_r360_metadata(path)

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe are required")
    def test_legacy_mp4_synthesizes_complete_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.r360.mp4"
            make_dual_track_recording(path, embed_full_result=False)
            result = RPI360Recording.open(path).calibration_result
            self.assertEqual(result["schema_version"], 1)
            self.assertEqual(result["diagnostics"]["source"], "legacy-rpi360-tag")

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe are required")
    def test_mismatched_mp4_tags_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mismatch.r360.mp4"
            make_dual_track_recording(path)
            metadata = read_r360_metadata(path)
            metadata["calibration"]["camera_0"]["K"][0][0] += 1.0
            write_r360_metadata(path, metadata)
            with self.assertRaisesRegex(MetadataError, "different K/D/R"):
                RPI360Recording.open(path)


if __name__ == "__main__":
    unittest.main()
