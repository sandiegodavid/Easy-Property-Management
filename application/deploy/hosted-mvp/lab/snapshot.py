"""Source-only deterministic lab archive; never copy workspaces, secrets or host tools."""

import argparse
from hashlib import sha256
import io
import json
from pathlib import Path
import tarfile

SKIP = {"tests", "__pycache__", "web_build"}
EXTRA = {
    "epm-h02-operator-v1",
    "epm-host-guardian.service",
    "Dockerfile.admin",
    "Dockerfile.operator",
}


def selected(application):
    for folder in ("apps/server/app", "deploy/hosted-mvp", "database/host-inventory-migrations"):
        for path in sorted((application / folder).rglob("*")):
            relative = path.relative_to(application)
            if any(part in SKIP for part in relative.parts):
                continue
            if path.is_symlink():
                raise ValueError("Symlinks are not qualification inputs")
            if path.is_file() and (
                path.suffix in {".py", ".c"}
                or (relative.parts[0] == "database" and path.suffix == ".ini")
                or path.name in EXTRA
            ):
                yield path, relative.as_posix()
    helper = application / "database/hosted_ddl.py"
    if helper.is_symlink():
        raise ValueError("Symlinks are not qualification inputs")
    if helper.is_file():
        yield helper, "database/hosted_ddl.py"


def snapshot(application, destination):
    application = application.resolve(strict=True)
    entries = [(name, path.read_bytes()) for path, name in selected(application)]
    pins = {name: sha256(data).hexdigest() for name, data in entries}
    manifest = {
        "version": 1,
        "files": pins,
        "source_sha256": sha256(json.dumps(pins, sort_keys=True).encode()).hexdigest(),
    }
    with destination.open("xb") as output, tarfile.open(fileobj=output, mode="w") as archive:
        for name, data in [
            *entries,
            ("qualification-source.json", json.dumps(manifest, sort_keys=True).encode()),
        ]:
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            archive.addfile(info, io.BytesIO(data))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(snapshot(args.application, args.output), sort_keys=True))
