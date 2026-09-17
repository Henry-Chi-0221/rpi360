"""Package Rust C ABI libraries without an App Store signing identity."""

import argparse
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
os.chdir(root)
cargo = shutil.which("cargo") or str(Path.home() / ".cargo/bin/cargo")
entries = [
    ("aarch64-apple-darwin", "macos-arm64", "macos", None),
    ("aarch64-apple-ios", "ios-arm64", "ios", None),
    ("aarch64-apple-ios-sim", "ios-arm64-simulator", "ios", "simulator"),
]
output = root / "packages/apple-sdk/RPI360Core.xcframework"
output.mkdir(exist_ok=True)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--mac-only", action="store_true", help="build only the local reference adapter"
)
args = parser.parse_args()
if args.mac_only:
    entries = entries[:1]
libraries = []
for target, identifier, platform, variant in entries:
    subprocess.run(
        [
            cargo,
            "build",
            "--release",
            "-p",
            "rpi360-ffi",
            "--features",
            "gpu",
            "--target",
            target,
        ],
        check=True,
    )
    dest = output / identifier
    headers = dest / "Headers"
    headers.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        root / f"target/{target}/release/librpi360_ffi.a", dest / "librpi360_ffi.a"
    )
    (headers / "rpi360.h").write_text(
        "#include <stdint.h>\n#include <stddef.h>\n"
        '#ifdef __cplusplus\nextern "C" {\n#endif\n'
        "char *rpi360_calibration(const char *json);\n"
        "char *rpi360_evaluate(const char *json, int64_t time_us);\n"
        "char *rpi360_map_rays(const char *json);\n"
        "void rpi360_free(char *result);\n"
        "char *rpi360_renderer_create(void **context);\n"
        "char *rpi360_renderer_upload(void *, const uint8_t *, "
        "size_t, uint32_t, uint32_t);\n"
        "char *rpi360_renderer_draw(void *, const char *, const char *, uint8_t *, "
        "size_t, uint32_t, uint32_t);\n"
        "void rpi360_renderer_free(void *context);\n"
        "#ifdef __cplusplus\n}\n#endif\n"
    )
    (headers / "module.modulemap").write_text(
        'module RPI360Core { header "rpi360.h" export * }\n'
    )
    item = {
        "LibraryIdentifier": identifier,
        "LibraryPath": "librpi360_ffi.a",
        "HeadersPath": "Headers",
        "SupportedArchitectures": ["arm64"],
        "SupportedPlatform": platform,
    }
    if variant:
        item["SupportedPlatformVariant"] = variant
    libraries.append(item)
with (output / "Info.plist").open("wb") as f:
    plistlib.dump(
        {
            "CFBundlePackageType": "XFWK",
            "XCFrameworkFormatVersion": "1.0",
            "AvailableLibraries": libraries,
        },
        f,
    )
print(output)
