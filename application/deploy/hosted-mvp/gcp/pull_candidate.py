"""Pull one exact owned candidate using an ephemeral host-identity credential."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

from cloud_plan import Target


def validate_reference(target, reference):
    prefix = target.region + "-docker.pkg.dev/" + target.project + "/" + target.repository + "/"
    if not reference.startswith(prefix) or not re.fullmatch(
        r"(admin|operator)@sha256:[a-f0-9]{64}", reference[len(prefix) :]
    ):
        raise ValueError("Use an exact manifest digest in this host's owned repository")
    return prefix.split("/", 1)[0]


def pull(target, reference):
    if os.geteuid() != 0:
        raise ValueError("Protected host pull requires root")
    registry = validate_reference(target, reference)
    request = Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urlopen(request, timeout=10) as response:
        token = json.loads(response.read(65536))["access_token"]
    with TemporaryDirectory(prefix="epm-registry-") as directory:
        auth = base64.b64encode(("oauth2accesstoken:" + token).encode()).decode()
        path = Path(directory) / "config.json"
        path.write_text(json.dumps({"auths": {registry: {"auth": auth}}}))
        path.chmod(0o600)
        subprocess.run(["docker", "--config", directory, "pull", reference], check=True)
    print("Exact owned candidate pulled; temporary credential removed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--reference", required=True)
    args = parser.parse_args()
    pull(Target.model_validate_json(args.target.read_text()), args.reference)
