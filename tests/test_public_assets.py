import json
import unittest
from pathlib import Path

from rpi360 import Player
from rpi360.common.metadata import (
    find_camera_tracks,
    probe_media,
    read_embedded_calibration_result,
)


class PublicAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]

    def test_example_calibration_is_complete_and_anonymized(self):
        path = self.root / "calibration/rpi5-dual-imx219-example.json"
        payload = path.read_text(encoding="utf-8")
        document = json.loads(payload)
        self.assertEqual(document["calibration_state"], "complete")
        self.assertEqual(
            document["calibration"]["camera_0"]["fisheye_fov_deg"],
            210.0,
        )
        for forbidden in ("/Users/", "/home/", "local_data", "Documents/"):
            self.assertNotIn(forbidden, payload)

    def test_curated_samples_are_small_valid_dual_h264_recordings(self):
        samples = sorted((self.root / "assets/samples").glob("*.r360.mp4"))
        self.assertEqual(
            [path.name for path in samples],
            ["lake.r360.mp4", "steps.r360.mp4", "waterfront.r360.mp4"],
        )
        for path in samples:
            self.assertLess(path.stat().st_size, 10 * 1024 * 1024)
            probe = probe_media(path)
            tracks = find_camera_tracks(path)
            self.assertEqual(
                [tracks["camera_0"]["id"], tracks["camera_1"]["id"]],
                ["0x1", "0x2"],
            )
            self.assertTrue(
                all(
                    stream["codec_name"] == "h264"
                    for stream in probe["streams"]
                    if stream.get("codec_type") == "video"
                )
            )
            video_streams = [
                stream
                for stream in probe["streams"]
                if stream.get("codec_type") == "video"
            ]
            self.assertTrue(
                all(
                    (int(stream["width"]), int(stream["height"]))
                    == (3280, 2464)
                    for stream in video_streams
                )
            )
            result = read_embedded_calibration_result(path)
            self.assertEqual(result["calibration_state"], "complete")
            with Player.mp4(
                path,
                paced=False,
                panorama_size=(256, 128),
                decode_size=(205, 154),
            ) as player:
                frame = player.next(timeout=None)
                self.assertIsNotNone(frame)
                self.assertEqual(frame.camera0.shape, (154, 205, 3))

    def test_readme_assets_and_links_exist(self):
        expected_images = (
            "hero.webp",
            "projection-grid.png",
            "tiny-planet.webp",
            "rabbit-hole.webp",
            "perspective-orbit.webp",
            "barrel-roll.webp",
            "aspect-ratios.webp",
        )
        showcase = self.root / "assets/showcase"
        for name in expected_images:
            path = showcase / name
            self.assertTrue(path.is_file(), name)
            self.assertGreater(path.stat().st_size, 1000)
        expected_clips = (
            "hero.mp4",
            "tiny-planet.mp4",
            "rabbit-hole.mp4",
            "perspective-orbit.mp4",
            "barrel-roll.mp4",
            "aspect-ratios.mp4",
        )
        for name in expected_clips:
            path = showcase / name
            self.assertTrue(path.is_file(), name)
            streams = [
                stream
                for stream in probe_media(path)["streams"]
                if stream.get("codec_type") == "video"
            ]
            self.assertEqual(len(streams), 1)
            self.assertEqual(streams[0]["codec_name"], "h264")
            self.assertEqual(
                (int(streams[0]["width"]), int(streams[0]["height"])),
                (1920, 1080),
            )
        for name in ("system_overview.jpeg", "projections.jpeg"):
            path = self.root / "assets" / name
            self.assertTrue(path.is_file(), name)
            self.assertGreater(path.stat().st_size, 1000)
        self.assertTrue(
            (self.root / "hardware/calibration/checkerboard-9x6-a4.pdf").is_file()
        )


if __name__ == "__main__":
    unittest.main()
