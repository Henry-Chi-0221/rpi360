"""Build a platform wheel containing the shared C ABI (no Python ABI coupling)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.bdist_wheel import bdist_wheel
from setuptools.command.build_py import build_py


class BuildCore(build_py):
    def run(self):
        super().run()
        cargo = shutil.which("cargo") or str(Path.home() / ".cargo/bin/cargo")
        subprocess.run(
            [cargo, "build", "--release", "--locked", "-p", "rpi360-ffi"], check=True
        )
        name = "librpi360_ffi." + ("dylib" if sys.platform == "darwin" else "so")
        target = Path(os.environ.get("CARGO_TARGET_DIR", "target")) / "release" / name
        shutil.copy2(target, Path(self.build_lib) / "rpi360/core" / name)


class PlatformWheel(bdist_wheel):
    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self):
        _, _, platform = super().get_tag()
        return "py3", "none", platform


setup(cmdclass={"build_py": BuildCore, "bdist_wheel": PlatformWheel})
