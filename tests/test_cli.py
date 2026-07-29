import unittest
from pathlib import Path

from rpi360.cli import build_parser


class CLITests(unittest.TestCase):
    def test_public_commands_match_the_single_console_entrypoint(self):
        parser = build_parser()
        subparsers = next(
            action
            for action in parser._actions
            if hasattr(action, "choices") and isinstance(action.choices, dict)
        )
        self.assertEqual(
            set(subparsers.choices),
            {
                "inspect",
                "play",
                "live",
                "record",
                "calibrate-cameras",
                "calibrate-rig",
            },
        )

    def test_no_standalone_image_options_exist(self):
        parser = build_parser()
        subparsers = next(
            action
            for action in parser._actions
            if hasattr(action, "choices") and isinstance(action.choices, dict)
        )
        options = {
            option
            for command in subparsers.choices.values()
            for action in command._actions
            for option in action.option_strings
        }
        self.assertNotIn("--image", options)
        self.assertNotIn("--camera0-images", options)
        self.assertNotIn("--camera1-images", options)
        self.assertNotIn("--backend", options)

    def test_both_calibration_stages_use_one_result_path(self):
        parser = build_parser()
        cameras = parser.parse_args(["calibrate-cameras", "calibration-result.json"])
        rig = parser.parse_args(["calibrate-rig", "calibration-result.json"])
        self.assertEqual(
            cameras.calibration,
            Path("calibration-result.json"),
        )
        self.assertEqual(rig.calibration, cameras.calibration)
        self.assertEqual(cameras.fisheye_fov, 210.0)
        self.assertIsNone(rig.equirectangular_size)
        self.assertEqual(rig.ransac_threshold, 0.4)
        self.assertEqual(rig.maximum_reprojection_error, 8.0)
        self.assertEqual(rig.quality, "reference")
        self.assertEqual(rig.samples, 20)
        self.assertEqual(rig.capture_seconds, 30.0)
        self.assertEqual(rig.opencv_threads, 2)
        self.assertFalse(hasattr(rig, "output"))
        self.assertFalse(hasattr(rig, "intrinsics"))


if __name__ == "__main__":
    unittest.main()
