"""Generate device OpenAPI from actual routes; emit versioned data contracts."""

import json
import tempfile
from pathlib import Path

import yaml
from rpi360_camera.api import create_app
from rpi360_camera.capture import CaptureEngine

root = Path(__file__).resolve().parents[2] / "schemas"
root.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as t:
    schema = create_app(CaptureEngine(t)).openapi()
    schema["components"]["securitySchemes"] = {
        "DeviceToken": {"type": "http", "scheme": "bearer"}
    }
    for path, methods in schema["paths"].items():
        if path not in ["/v1/info", "/v1/pair"]:
            for _method, operation in methods.items():
                operation["security"] = [{"DeviceToken": []}]
    schema["paths"]["/v1/pair"]["delete"]["security"] = [{"DeviceToken": []}]
    (root / "device-api.openapi.yaml").write_text(
        yaml.safe_dump(schema, sort_keys=False)
    )
with tempfile.TemporaryDirectory() as t:
    from rpi360_worker.api import create_app as worker_app

    (root / "worker-api.openapi.yaml").write_text(
        yaml.safe_dump(
            worker_app(t, "schema-generation-token-32-characters").openapi(),
            sort_keys=False,
        )
    )
num = {"type": "number"}
integer = {"type": "integer"}
positive = {"type": "integer", "minimum": 1}


def array(item, n=None):
    return {
        "type": "array",
        "items": item,
        **({"minItems": n, "maxItems": n} if n else {}),
    }


def obj(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": required or list(properties),
        "additionalProperties": False,
    }


def write(name, value):
    value = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://rpi360.dev/schemas/{name}.schema.json",
        **value,
    }
    (root / f"{name}.schema.json").write_text(json.dumps(value, indent=2) + "\n")


view = obj(
    {
        "orientation": array(num, 4),
        "horizontal_fov_deg": {"type": "number", "exclusiveMinimum": 0, "maximum": 359},
        "projection": {"enum": ["perspective", "stereographic", "equirectangular"]},
        "spin_deg": num,
    }
)
write(
    "project",
    obj(
        {
            "schema_version": {"const": 2},
            "id": {"type": "string", "minLength": 1},
            "source_id": {"type": "string", "minLength": 1},
            "duration_us": positive,
            "keyframes": {
                **array(
                    obj(
                        {
                            "time_us": {"type": "integer", "minimum": 0},
                            "view": view,
                            "linear": {"type": "boolean"},
                        }
                    )
                ),
                "minItems": 1,
            },
            "time_remap": {
                **array(
                    obj(
                        {
                            "output_us": {"type": "integer", "minimum": 0},
                            "source_us": {"type": "integer", "minimum": 0},
                        }
                    )
                ),
                "minItems": 1,
            },
            "alignment_us": {"type": ["integer", "null"]},
        }
    ),
)
lens = obj(
    {
        "size": array(positive, 2),
        "intrinsics": array(num, 4),
        "skew": num,
        "distortion": array(num, 4),
        "fov_deg": {"type": "number", "exclusiveMinimum": 0, "maximum": 360},
        "camera_to_rig": array(array(num, 3), 3),
        "gain": array(num, 3),
    }
)
write(
    "calibration",
    obj(
        {
            "schema_version": {"const": 2},
            "id": {"type": "string"},
            "coordinate_system": {"const": "right-up-back"},
            "cameras": array(lens, 2),
        }
    ),
)
stream = {
    "type": "object",
    "required": ["camera", "path", "width", "height", "codec", "frames"],
    "properties": {
        "camera": {"enum": [0, 1]},
        "path": {"type": "string", "pattern": "^camera[01]\\.mp4$"},
        "width": positive,
        "height": positive,
        "nominal_fps": num,
        "codec": {"const": "h264"},
        "frames": {"type": "integer", "minimum": 0},
        "media_start_offset_us": integer,
        "last_pts_us": {"type": ["integer", "null"]},
        "metadata_frames": integer,
    },
    "additionalProperties": False,
}
write(
    "recording",
    obj(
        {
            "schema_version": {"const": 2},
            "id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
            "state": {
                "enum": [
                    "recording",
                    "complete",
                    "recovery_required",
                    "recovering",
                    "recovered",
                ]
            },
            "created_at": {"type": "string"},
            "clock": obj(
                {
                    "epoch": {"type": "string"},
                    "origin_sensor_ns": {
                        "type": ["string", "null"],
                        "pattern": "^[0-9]+$",
                    },
                    "unit": {"const": "microseconds"},
                }
            ),
            "streams": array(stream, 2),
            "calibration": {"type": ["string", "null"]},
            "sync": obj(
                {
                    "method": {"enum": ["libcamera-software", "unknown"]},
                    "tolerance_us": {"type": ["integer", "null"], "minimum": 1},
                }
            ),
            "files": array(
                obj(
                    {
                        "path": {"type": "string", "pattern": "^[a-zA-Z0-9_.-]+$"},
                        "bytes": {"type": "integer", "minimum": 0},
                        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    }
                )
            ),
            "error": {"type": "string"},
            "recovered_from": {"type": "string"},
        },
        [
            "schema_version",
            "id",
            "state",
            "created_at",
            "clock",
            "streams",
            "calibration",
            "sync",
            "files",
        ],
    ),
)
