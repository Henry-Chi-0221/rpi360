import json
from pathlib import Path

import jsonschema
from rpi360.core import convert_calibration, evaluate_project

ROOT = Path(__file__).resolve().parents[2]


def test_recipes_use_real_valid_projects_and_calibrations():
    for path in (ROOT / "demos/recipes").glob("*.json"):
        recipe = json.loads(path.read_text())
        for kind in ("project", "calibration"):
            jsonschema.validate(
                recipe[kind],
                json.loads((ROOT / f"schemas/{kind}.schema.json").read_text()),
            )
        for t in (
            0,
            recipe["project"]["duration_us"] // 2,
            recipe["project"]["duration_us"],
        ):
            evaluated = evaluate_project(recipe["project"], t)
            assert len(evaluated["view"]["orientation"]) == 4


def test_legacy_mount_conversion_explicit():
    p = convert_calibration(
        json.loads((ROOT / "calibration/rpi5-dual-imx219-example.json").read_text())
    )
    assert p["coordinate_system"] == "right-up-back"
    jsonschema.validate(
        p, json.loads((ROOT / "schemas/calibration.schema.json").read_text())
    )
