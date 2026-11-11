"""Explicit fresh-environment host-agent candidate installation, never service setup."""

import argparse
from pathlib import Path
import subprocess
import sys

from verify_build_inputs import verify


def install(bundle, destination):
    if sys.version_info[:2] != (3, 14) or destination.exists() or destination.is_symlink():
        raise RuntimeError("Use Python 3.14 and a fresh private installation destination.")
    wheel = verify(bundle)
    subprocess.run([sys.executable, "-m", "venv", "--copies", str(destination)], check=True)
    python = destination / "bin/python"
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-compile",
            "--find-links",
            str(bundle / "wheelhouse"),
            "--require-hashes",
            "-r",
            str(bundle / "dependencies.lock"),
        ],
        check=True,
    )
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--no-compile",
            str(wheel),
        ],
        check=True,
    )
    subprocess.run(
        [
            str(python),
            "-B",
            str(bundle / "stage_schema_resources.py"),
            str(bundle / "resources"),
            "--component",
            "host_agent",
        ],
        check=True,
    )
    subprocess.run(
        [str(python), "-B", str(bundle / "verify_installation.py"), "--component", "host_agent"],
        check=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    install(Path(__file__).resolve().parent, args.destination.absolute())
