import json
import struct
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
        samples = sorted((self.root / "fixtures/legacy-recordings").glob("*.r360.mp4"))
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
                    (int(stream["width"]), int(stream["height"])) == (3280, 2464)
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
        import re

        from PIL import Image

        for readme in ("README.md",):
            for target in re.findall(
                r"\]\(([^)]+)\)", (self.root / readme).read_text()
            ):
                if "://" not in target and not target.startswith("#"):
                    self.assertTrue((self.root / target.split("#")[0]).exists(), target)
        for recipe in (self.root / "demos/recipes").glob("*.json"):
            data = json.loads(recipe.read_text())
            self.assertEqual(data["output"]["fps"], 30)
            self.assertNotIn("rabbit", recipe.name)
            with Image.open(
                self.root / "demos/posters" / (recipe.stem + ".jpg")
            ) as image:
                ratio = data["output"]["width"] / data["output"]["height"]
                self.assertAlmostEqual(image.width / image.height, ratio, places=2)

    def test_hardware_photos_and_printable_stls_are_valid(self):
        hardware_assets = self.root / "hardware/photos"
        expected_images = (
            "assembled-on-tripod.jpg",
            "cad-overview.png",
            "camera-face.jpg",
            "enclosure-mount.jpg",
            "open-enclosure.jpg",
            "power-bank-fit.jpg",
            "rig-side.jpg",
        )
        for name in expected_images:
            path = hardware_assets / name
            self.assertTrue(path.is_file(), name)
            self.assertGreater(path.stat().st_size, 10_000)

        expected_extents = {
            "top-half.stl": (60.0, 113.8, 5.0),
            "bottom-half.stl": (60.0, 113.8, 41.0),
        }
        cad_directory = self.root / "hardware/cad"
        license_text = (cad_directory / "LICENSE").read_text(encoding="utf-8")
        notice_text = (cad_directory / "NOTICE").read_text(encoding="utf-8")
        self.assertIn(
            "CERN Open Hardware Licence Version 2 - Permissive",
            license_text,
        )
        self.assertIn("Copyright (c) 2026 Henry Chi", notice_text)
        for name, expected in expected_extents.items():
            data = (cad_directory / name).read_bytes()
            triangle_count = struct.unpack_from("<I", data, 80)[0]
            self.assertEqual(len(data), 84 + triangle_count * 50)
            minimum = [float("inf")] * 3
            maximum = [float("-inf")] * 3
            for index in range(triangle_count):
                values = struct.unpack_from("<12fH", data, 84 + index * 50)
                for vertex in range(3):
                    for axis, value in enumerate(
                        values[3 + vertex * 3 : 6 + vertex * 3]
                    ):
                        minimum[axis] = min(minimum[axis], value)
                        maximum[axis] = max(maximum[axis], value)
            actual = tuple(
                round(high - low, 1)
                for low, high in zip(minimum, maximum, strict=False)
            )
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
