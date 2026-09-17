"""Shared Rust core through a small C ABI; no independent Python geometry.

Set RPI360_CORE_LIBRARY for installed native artifacts. Source checkouts also
resolve their locally built library in target/release.
"""

import ctypes
import json
import os
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _library():
    suffix = "dylib" if sys.platform == "darwin" else "so"
    name = "librpi360_ffi." + suffix
    explicit = os.environ.get("RPI360_CORE_LIBRARY")
    roots = [p / "target/release" / name for p in Path(__file__).resolve().parents]
    paths = (
        ([Path(explicit)] if explicit else [])
        + [Path(__file__).with_name(name)]
        + roots
    )
    path = next((p for p in paths if p.is_file()), None)
    if path is None:
        raise RuntimeError(
            "Build the shared core with cargo build --release -p rpi360-ffi, "
            "or set RPI360_CORE_LIBRARY"
        )
    lib = ctypes.CDLL(str(path))
    lib.rpi360_calibration.argtypes = [ctypes.c_char_p]
    lib.rpi360_calibration.restype = ctypes.c_void_p
    lib.rpi360_evaluate.argtypes = [ctypes.c_char_p, ctypes.c_int64]
    lib.rpi360_evaluate.restype = ctypes.c_void_p
    lib.rpi360_map_rays.argtypes = [ctypes.c_char_p]
    lib.rpi360_map_rays.restype = ctypes.c_void_p
    lib.rpi360_free.argtypes = [ctypes.c_void_p]
    return lib


def _call(name, value, *args):
    lib = _library()
    ptr = getattr(lib, name)(json.dumps(value, allow_nan=False).encode(), *args)
    if not ptr:
        raise RuntimeError("Native core returned no result")
    try:
        result = json.loads(ctypes.string_at(ptr))
    finally:
        lib.rpi360_free(ptr)
    if isinstance(result, dict) and "error" in result:
        raise ValueError(result["error"])
    return result


def convert_calibration(value):
    return _call("rpi360_calibration", value)


def evaluate_project(project, time_us):
    return _call("rpi360_evaluate", project, int(time_us))


def map_rays(calibration, rays):
    return _call("rpi360_map_rays", {"calibration": calibration, "rays": rays})
