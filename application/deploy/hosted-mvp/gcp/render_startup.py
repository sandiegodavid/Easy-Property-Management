"""Render reviewed exact Docker package downloads into supported GCE startup metadata."""

import argparse
from pathlib import Path
import json
import re
import shlex
from urllib.parse import urlsplit

PACKAGES = {"docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin"}


def render(template, pins):
    if {pin["package"] for pin in pins} != PACKAGES or len(pins) != len(PACKAGES):
        raise ValueError("The closed four-package Docker input set is required")
    lines = ["install -d -m 0700 /var/cache/epm-host"]
    files = []
    for pin in pins:
        url, digest = pin["url"], pin["sha256"]
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "download.docker.com"
            or not parsed.path.startswith("/linux/ubuntu/dists/noble/pool/stable/amd64/")
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
        ):
            raise ValueError("Exact official AMD64 package URL/hash required")
        output = "/var/cache/epm-host/" + pin["package"] + ".deb"
        files.append(output)
        lines.append(
            "curl --fail --silent --show-error --location --proto '=https' "
            + shlex.quote(url)
            + " --output "
            + shlex.quote(output)
        )
        lines.append("printf '%s\\n' " + shlex.quote(digest + "  " + output) + " | sha256sum -c -")
    lines.append("apt-get install -y " + " ".join(files))
    lines.append("apt-mark hold " + " ".join(sorted(PACKAGES)))
    return template.replace("@@PINNED_DOCKER_PACKAGES@@", "\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pins", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x") as output:
        output.write(
            render(
                Path(__file__).with_name("startup.sh").read_text(),
                json.loads(args.pins.read_text())["packages"],
            )
        )
