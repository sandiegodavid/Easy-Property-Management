"""Protected verifier artifacts. RPC accepts IDs, never asserted measurement JSON."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import canonical
from app.modules.hosted_admin.application.qualification import (
    CapacitySnapshot,
    QualificationEvidence,
)

MAX_REPORT_BYTES = 65536
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


class VerifiedReports:
    def __init__(self, directory, inventory_digest):
        self.directory, self.inventory_digest = Path(directory), inventory_digest

    def _read(self, path, maximum):
        # Both files and all ancestors must be protected; symlinked reports,
        # tools and directories cannot supply evidence under a trusted identity.
        for parent in (path.parent, *path.parent.parents):
            info = parent.lstat()
            sticky = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid not in {0, os.geteuid()}
                or (info.st_mode & 0o022 and not sticky)
            ):
                raise AdminError("admin_verifier_path_unsafe", 503)
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_mode & 0o077
        ):
            raise AdminError("admin_verifier_artifact_unsafe", 503)
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o077
            ):
                raise AdminError("admin_verifier_artifact_unsafe", 503)
            raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise AdminError("admin_verifier_artifact_too_large", 413)
        return raw

    def report(self, identifier):
        if identifier != "capacity" and not re.fullmatch(
            r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}", identifier
        ):
            raise AdminError("admin_verifier_identity_invalid", 400)
        envelope = json.loads(self._read(self.directory / f"{identifier}.json", MAX_REPORT_BYTES))
        if set(envelope) != {"payload", "signature", "verifier_digest", "inventory_digest"}:
            raise AdminError("admin_verifier_report_invalid", 409)
        pinned = json.loads(self._read(self.directory / "verifier.json", MAX_REPORT_BYTES))
        key = self._read(self.directory / "verifier.key", 128)
        unsigned = {name: value for name, value in envelope.items() if name != "signature"}
        if (
            len(key) < 32
            or pinned != {"verifier_digest": envelope["verifier_digest"]}
            or not hmac.compare_digest(
                hmac.digest(key, canonical(unsigned).encode(), "sha256").hex(),
                envelope["signature"],
            )
        ):
            raise AdminError("admin_verifier_signature_invalid", 409)
        if identifier == "capacity" and envelope["inventory_digest"] != self.inventory_digest():
            raise AdminError("admin_capacity_inventory_changed", 409)
        return envelope["payload"]

    def snapshot(self):
        return CapacitySnapshot.model_validate(self.report("capacity"))

    def publish(self, identifier, payload):
        """Private verifier output only; never exposed by the broker vocabulary."""
        if not re.fullmatch(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}", identifier):
            raise AdminError("admin_verifier_identity_invalid", 400)
        pinned = json.loads(self._read(self.directory / "verifier.json", MAX_REPORT_BYTES))
        key = self._read(self.directory / "verifier.key", 128)
        if len(key) < 32 or set(pinned) != {"verifier_digest"}:
            raise AdminError("admin_verifier_signature_invalid", 409)
        unsigned = {
            "payload": payload,
            "verifier_digest": pinned["verifier_digest"],
            "inventory_digest": self.inventory_digest(),
        }
        encoded = canonical(
            unsigned | {"signature": hmac.digest(key, canonical(unsigned).encode(), "sha256").hex()}
        ).encode()
        if len(encoded) > MAX_REPORT_BYTES:
            raise AdminError("admin_verifier_artifact_too_large", 413)
        descriptor, temporary = tempfile.mkstemp(dir=self.directory, prefix=".verification-")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / f"{identifier}.json")
            directory = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def evidence(self, identifier):
        report = QualificationEvidence.model_validate(self.report(identifier))
        artifact = self._read(self.directory / f"{identifier}.evidence", MAX_ARTIFACT_BYTES)
        if (
            report.id != identifier
            or hashlib.sha256(artifact).hexdigest() != report.artifact_digest
        ):
            raise AdminError("admin_verifier_artifact_changed", 409)
        return report
