"""Resolve hash-locked binary dependencies inside the actual pinned Linux image."""

import argparse
from email import message_from_bytes
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import sys
import tomllib
from zipfile import ZipFile


def resolve(project, output, architecture):
    expected = {"amd64": "x86_64", "arm64": "aarch64"}[architecture]
    if (
        platform.system() != "Linux"
        or platform.machine() != expected
        or sys.version_info[:2] != (3, 14)
    ):
        raise RuntimeError("Resolve in the pinned target Linux/Python image, not on the Mac host.")
    if output.exists():
        raise RuntimeError("Use a fresh private resolution directory.")
    requirements = tomllib.loads(project.read_text())["project"]["dependencies"]
    output.mkdir(mode=0o700)
    wheels = output / "wheels"
    wheels.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--index-url",
            "https://pypi.org/simple",
            "--only-binary=:all:",
            "--dest",
            str(wheels),
            *requirements,
        ],
        check=True,
    )
    pins = []
    for path in sorted(wheels.glob("*.whl")):
        with ZipFile(path) as archive:
            entry = next(
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            )
            metadata = message_from_bytes(archive.read(entry))
        pins.append(
            {
                "name": metadata["Name"],
                "version": metadata["Version"],
                "filename": path.name,
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
        )
    if len({pin["name"].lower().replace("_", "-") for pin in pins}) != len(pins):
        raise RuntimeError("Duplicate dependency resolution.")
    lines = [f"{pin['name']}=={pin['version']} --hash=sha256:{pin['sha256']}" for pin in pins]
    (output / "dependencies.lock").write_text("\n".join(lines) + "\n")
    (output / "resolution.json").write_text(
        json.dumps(
            {
                "version": 1,
                "system": platform.system(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "requirements": requirements,
                "project_sha256": sha256(project.read_bytes()).hexdigest(),
                "distributions": pins,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--architecture", choices=("amd64", "arm64"), default="amd64")
    arguments = parser.parse_args()
    resolve(arguments.project, arguments.output, arguments.architecture)
