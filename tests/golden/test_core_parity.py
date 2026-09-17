import json
import subprocess
from pathlib import Path

import numpy as np
from rpi360.common.metadata import calibration_profile_from_result
from rpi360.common.rendering import camera1_mount_rotation, project_unit_rays_to_fisheye
from rpi360.core import evaluate_project, map_rays

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_native_wasm_geometry_within_half_source_pixel():
    cal = json.loads((ROOT / "calibration/rpi5-dual-imx219-example.json").read_text())
    rng = np.random.default_rng(20260917)
    rays = rng.normal(size=(1024, 3))
    rays /= np.linalg.norm(rays, axis=1, keepdims=True)
    native = map_rays(cal, rays.tolist())
    output = subprocess.check_output(
        ["node", str(ROOT / "tests/golden/core-wasm.mjs")],
        input=json.dumps({"calibration": cal, "rays": rays.tolist()}).encode(),
    )
    wasm = json.loads(output)
    legacy = calibration_profile_from_result(cal)
    old = rays @ np.diag([1, -1, -1])
    for i, camera in enumerate([legacy.camera0, legacy.camera1]):
        cam_rays = (
            old if i == 0 else old @ legacy.R_cam1_to_cam0 @ camera1_mount_rotation()
        )
        x, y, valid, _ = project_unit_rays_to_fisheye(
            cam_rays, camera, camera.width, camera.height
        )
        for j in range(len(rays)):
            if valid[j] and native[j][i] is not None:
                expected = np.array([x[j], y[j]])
                actual = np.array(native[j][i][0]) * [camera.width, camera.height]
                assert np.max(np.abs(expected - actual)) < 0.5
            if native[j][i] is not None:
                assert (
                    np.max(np.abs(np.array(native[j][i][0]) - np.array(wasm[j][i][0])))
                    * max(camera.width, camera.height)
                    < 0.5
                )


def test_project_pose_and_source_time_match_wasm():
    p = json.loads((ROOT / "demos/recipes/barrel-roll.json").read_text())["project"]
    for t in [0, 1234567, 4000000, 7900000, 8000000]:
        native = evaluate_project(p, t)
        wasm = json.loads(
            subprocess.check_output(
                ["node", str(ROOT / "tests/golden/core-wasm.mjs")],
                input=json.dumps({"project": p, "time_us": t}).encode(),
            )
        )
        assert native["source_time_us"] == wasm["source_time_us"]
        assert np.allclose(
            native["view"]["orientation"], wasm["view"]["orientation"], atol=1e-6
        )
        assert abs(native["view"]["spin_deg"] - wasm["view"]["spin_deg"]) < 1e-4
