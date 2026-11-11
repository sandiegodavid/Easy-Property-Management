"""Validate one protected Tunnel credential; never put its bytes in reports or environment."""

import base64
import json
import os
from pathlib import Path
import stat

from app.modules.host_agent.application.dispatch import HostAgentDenied

MAX_CREDENTIAL_BYTES = 4096


def protected_bytes(path: Path, *, owner=0, limit=MAX_CREDENTIAL_BYTES):
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise HostAgentDenied()
    parent = path.parent.stat()
    if parent.st_uid != owner or stat.S_IMODE(parent.st_mode) & 0o077:
        raise HostAgentDenied()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != owner
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > limit
        ):
            raise HostAgentDenied()
        data = os.read(descriptor, limit + 1)
        if len(data) > limit:
            raise HostAgentDenied()
        return data
    finally:
        os.close(descriptor)


def validate_tunnel_credential(path, tunnel_id, *, owner=0):
    try:
        value = json.loads(protected_bytes(path, owner=owner))
        if (
            set(value) != {"AccountTag", "TunnelSecret", "TunnelID"}
            or value["TunnelID"] != tunnel_id
            or not isinstance(value["AccountTag"], str)
            or len(value["AccountTag"]) != 32
            or any(char not in "0123456789abcdef" for char in value["AccountTag"])
            or len(base64.b64decode(value["TunnelSecret"], validate=True)) != 32
        ):
            raise HostAgentDenied()
    except Exception:
        # Do not retain a JSON/Pydantic cause containing credential material.
        raise HostAgentDenied() from None
