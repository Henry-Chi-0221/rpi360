import runpy
import sys
import unittest
from pathlib import Path
from unittest import mock


class ExampleImportTests(unittest.TestCase):
    def test_examples_have_no_import_side_effects(self):
        root = Path(__file__).resolve().parents[1] / "examples"
        for path in sorted(root.glob("*/*.py")):
            namespace = runpy.run_path(str(path), run_name="rpi360_example")
            self.assertIn("main", namespace, str(path))

    def test_rig_example_uses_only_the_record_then_solve_workflow(self):
        root = Path(__file__).resolve().parents[1]
        namespace = runpy.run_path(
            str(root / "examples/rpi/calibrate_rig.py"),
            run_name="rpi360_example",
        )
        self.assertIn("RigCalibrationWorkflow", namespace)
        self.assertNotIn("RigCalibrationSession", namespace)
        self.assertNotIn("RigVideoRecorder", namespace)

    def test_aspect_ratio_example_uses_public_viewer_arguments(self):
        root = Path(__file__).resolve().parents[1]
        namespace = runpy.run_path(
            str(root / "examples/playback/aspect_ratios.py"),
            run_name="rpi360_example",
        )
        calls = []

        class FakePlayer:
            @classmethod
            def mp4(cls, *args, **kwargs):
                del cls

                class Context:
                    def __enter__(self):
                        return "player"

                    def __exit__(self, *exc):
                        return False

                calls.append(("mp4", args, kwargs))
                return Context()

        def fake_viewer(player, **kwargs):
            calls.append(("viewer", player, kwargs))

        namespace["main"].__globals__["Player"] = FakePlayer
        namespace["main"].__globals__["run_viewer"] = fake_viewer
        with mock.patch.object(
            sys,
            "argv",
            ["aspect_ratios.py", "input.mp4", "--aspect-ratio", "9:16"],
        ):
            namespace["main"]()

        self.assertEqual(calls[-1], ("viewer", "player", {"window": "RPI360 9:16"}))


if __name__ == "__main__":
    unittest.main()
