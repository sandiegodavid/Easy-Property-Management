"""Verify pinned build bytes before installing wheels; stdlib only, no target imports."""

from hashlib import sha256
import json
from pathlib import Path
import re
import sys


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def verify(root):
    manifest = json.loads((root / "resources/hosted-candidate.json").read_text())
    wheels = list(root.glob("*.whl"))
    if len(wheels) != 1 or digest(wheels[0]) != manifest["wheel_sha256"]:
        raise ValueError("Candidate wheel bytes do not match.")
    lock = root / "dependencies.lock"
    if digest(lock) != manifest["dependency_lock_sha256"]:
        raise ValueError("Candidate dependency lock does not match.")
    expected = set()
    for line in lock.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"[A-Za-z0-9_.-]+==[^\s]+ --hash=sha256:([0-9a-f]{64})", line)
        if not match:
            raise ValueError("Dependencies require exact versions and artifact hashes.")
        expected.add(match[1])
    files = list((root / "wheelhouse").iterdir())
    if any(path.is_symlink() or path.suffix != ".whl" for path in files):
        raise ValueError("Unexpected wheelhouse input.")
    if {digest(path) for path in files} != expected or len(files) != len(expected):
        raise ValueError("Dependency wheel bytes do not match the closed lock.")
    return wheels[0]


if __name__ == "__main__":
    verify(Path(sys.argv[1]))
