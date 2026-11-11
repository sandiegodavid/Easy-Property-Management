"""Archive a verified agent bundle deterministically; never overwrite prior evidence."""

import argparse
import gzip
import json
from pathlib import Path
import tarfile

from verify_build_inputs import verify

EPOCH = 1704067200


def archive(bundle, destination):
    verify(bundle)
    manifest = bundle / "resources/hosted-candidate.json"
    declaration = json.loads(manifest.read_text())
    if declaration["component"] != "host_agent":
        raise ValueError("A prepared host-agent bundle is required.")
    paths = sorted(bundle.rglob("*"))
    if bundle.is_symlink() or any(
        path.is_symlink() or not (path.is_file() or path.is_dir()) for path in paths
    ):
        raise ValueError("Only regular bundle files and directories may be archived.")
    expected = {
        "dependencies.lock",
        "install_agent.py",
        "verify_build_inputs.py",
        "stage_schema_resources.py",
        "verify_installation.py",
        "resources/hosted-candidate.json",
        *[path.name for path in bundle.glob("*.whl")],
        *["wheelhouse/" + path.name for path in (bundle / "wheelhouse").iterdir()],
        *["resources/" + pin["path"] for pin in declaration["files"] if pin["root"] == "resources"],
    }
    if {path.relative_to(bundle).as_posix() for path in paths if path.is_file()} != expected:
        raise ValueError("Unexpected agent bundle files.")
    with destination.open("xb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                for path in paths:
                    if not path.is_file():
                        continue
                    info = tar.gettarinfo(str(path), path.relative_to(bundle).as_posix())
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = EPOCH
                    info.mode = 0o644
                    with path.open("rb") as content:
                        tar.addfile(info, content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    archive(args.bundle, args.destination)
