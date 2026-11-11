"""Fresh hosted launch inputs, supplied by a read-only protected host mount."""

import json
import os
from pathlib import Path
import re
import stat
from typing import Literal
from urllib.parse import urlsplit

from pydantic import model_validator

from app.platform.hosted_artifacts import ArtifactInvalid
from app.platform.hosted_contracts.values import CanonicalId, Contract, Revision

MAX_BINDING_BYTES = 8192
MAX_DNS_NAME = 253
MIN_DNS_LABELS = 2


class LaunchBinding(Contract):
    version: Literal[1] = 1
    component: Literal["operator", "admin"]
    deployment_id: CanonicalId
    origin: str
    control_path: str
    operator_id: CanonicalId | None = None
    workspace_id: CanonicalId | None = None
    workspace_path: str | None = None
    resource_generation: Revision

    @model_validator(mode="after")
    def validate_binding(self):
        origin = urlsplit(self.origin)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.netloc != origin.hostname
            or self.origin != "https://" + origin.hostname
            or len(origin.hostname) > MAX_DNS_NAME
            or len(origin.hostname.split(".")) < MIN_DNS_LABELS
            or not all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
                for part in origin.hostname.split(".")
            )
        ):
            raise ValueError("An exact HTTPS origin is required.")
        operator_fields = (self.operator_id, self.workspace_id, self.workspace_path)
        if self.component == "operator" and not all(operator_fields):
            raise ValueError("An Operator binding is required.")
        if self.component == "admin" and any(value is not None for value in operator_fields):
            raise ValueError("Admin cannot select an Operator workspace.")
        paths = [Path(self.control_path)]
        if self.workspace_path is not None:
            paths.append(Path(self.workspace_path))
        if any(not p.is_absolute() or p.resolve(strict=True) != p or not p.is_dir() for p in paths):
            raise ValueError("Existing canonical mount paths are required.")
        if len(paths) > 1 and (
            paths[0] == paths[1] or any(p in q.parents for p, q in (paths, paths[::-1]))
        ):
            raise ValueError("Separate workspace and control mounts are required.")
        return self


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactInvalid()
        result[key] = value
    return result


def load_binding(path: Path, component: str) -> LaunchBinding:
    """No environment/local config fallback; no creation, identity inference or writes."""
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ArtifactInvalid()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) & 0o022
            or info.st_nlink != 1
            or info.st_size > MAX_BINDING_BYTES
        ):
            raise ArtifactInvalid()
        data = os.read(descriptor, MAX_BINDING_BYTES + 1)
        if len(data) > MAX_BINDING_BYTES:
            raise ArtifactInvalid()
        binding = LaunchBinding.model_validate(json.loads(data, object_pairs_hook=_unique))
        if binding.component != component:
            raise ArtifactInvalid()
        return binding
    finally:
        os.close(descriptor)
