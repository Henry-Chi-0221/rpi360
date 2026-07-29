import runpy
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
