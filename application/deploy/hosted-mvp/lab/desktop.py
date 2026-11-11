"""Mac Docker candidate checks; evidence is Desktop/emulated, never native qualification."""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import subprocess


def docker(*arguments):
    return subprocess.run(
        ["docker", *arguments], check=True, capture_output=True, text=True, timeout=180
    ).stdout.strip()


def image_id(value):
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise argparse.ArgumentTypeError("Use an immutable local image ID, not a tag")
    return value


def check(component, image):
    record = json.loads(docker("image", "inspect", image))[0]
    assert record["Id"] == image and record["Os"] == "linux"
    assert record["Config"]["Labels"]["epm.component"] == component
    fixture = str(Path(__file__).resolve().parents[1] / "probe.py")
    options = [
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--network=none",
        "--memory=512m",
        "--pids-limit=64",
        "--tmpfs=/tmp:rw,nosuid,nodev,size=256m",
        "--workdir=/tmp",
    ]
    result = docker(
        "run",
        "--rm",
        *options,
        "--mount",
        f"type=bind,src={fixture},dst=/probe.py,readonly",
        "--entrypoint",
        "/opt/epm/venv/bin/python",
        image,
        "-B",
        "/probe.py",
        "--component",
        component,
    )
    probe = json.loads(result)
    assert probe["normalStartup"] == "blocked"
    return {"image": image, "architecture": record["Architecture"], "probe": probe}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin", type=image_id, required=True)
    parser.add_argument("--operator", type=image_id, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Reserve output before running anything; failed evidence is never overwritten.
    with args.output.open("x") as output:
        report = {
            "scope": "desktop-linux-not-native-or-gcp",
            "status": "failed",
            "at": datetime.now(UTC).isoformat(),
            "components": {},
        }
        try:
            report["engine"] = json.loads(docker("version", "--format", "{{json .}}"))
            for component in ("admin", "operator"):
                report["components"][component] = check(component, getattr(args, component))
            report["status"] = "desktop_component_pass"
        finally:
            output.write(json.dumps(report, indent=2) + "\n")
