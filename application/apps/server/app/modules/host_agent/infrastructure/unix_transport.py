"""Bounded private Unix transport; kernel credentials precede parsing/admission.

Not registered with FastAPI or startup. The restricted control client is a separate
OS principal from public Admin. H04 supplies live admitted-intent verification.
"""

from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys
from typing import Literal

from app.modules.host_agent.application.dispatch import (
    HostAgentDenied,
    HostAgentUnavailable,
    HostEffect,
    EffectReceipt,
)
from app.platform.hosted_contracts.operations import SemanticConflict
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import Contract

MAX_FRAME = 32768


class Call(Contract):
    version: Literal[1] = 1
    method: Literal["execute", "original"]
    command: HostEffect


def invoke(path: Path, call: Call, *, expected_agent_uid: int):
    """Restricted local client: authenticate the agent before disclosing the call.

    Lost/truncated/malformed responses are unavailable, never a fresh retry identity.
    The caller retains its original parent/child request and checks that receipt.
    """
    if not path.is_absolute() or path.parent.resolve() != path.parent:
        raise HostAgentDenied()
    encoded = call.model_dump_json().encode()
    if len(encoded) > MAX_FRAME:
        raise HostAgentDenied()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(5)
            connection.connect(str(path))
            if peer_uid(connection) != expected_agent_uid:
                raise HostAgentDenied()
            connection.sendall(struct.pack("!I", len(encoded)) + encoded)
            length = struct.unpack("!I", _read(connection, 4, unavailable=True))[0]
            if not 0 < length <= MAX_FRAME:
                raise HostAgentUnavailable()
            response = json.loads(
                _read(connection, length, unavailable=True), object_pairs_hook=_unique_object
            )
        if not isinstance(response, dict) or set(response) != {"result"}:
            if response == {"error": {"code": "host_agent_denied"}}:
                raise HostAgentDenied()
            if response == {"error": {"code": "hosted_operation_conflict"}}:
                raise SemanticConflict()
            raise HostAgentUnavailable()
        result = EffectReceipt.model_validate(response["result"])
        command = call.command
        if (
            result.operation_id != command.effect.child_id()
            or result.parent_operation_id != command.effect.parent.operation_id
            or result.binding_id != command.effect.binding_id
            or result.request_hash != semantic_hash(command)
            or result.idempotency_key != command.effect.child_key()
        ):
            raise HostAgentUnavailable()
        return result
    except SemanticConflict:
        raise
    except (OSError, ValueError, RecursionError) as error:
        raise HostAgentUnavailable() from error


def peer_uid(connection: socket.socket) -> int:
    if connection.family != socket.AF_UNIX:
        raise HostAgentDenied()
    if sys.platform.startswith("linux"):
        credentials = connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
        )
        _, uid, _ = struct.unpack("3i", credentials)
        return uid
    if hasattr(connection, "getpeereid"):
        uid, _ = connection.getpeereid()
        return uid
    if sys.platform == "darwin":
        # Python's socket wrapper need not expose the OS getpeereid(3) API.
        function = ctypes.CDLL(None, use_errno=True).getpeereid
        function.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        ]
        function.restype = ctypes.c_int
        uid, gid = ctypes.c_uint(), ctypes.c_uint()
        if function(connection.fileno(), ctypes.byref(uid), ctypes.byref(gid)) == 0:
            return uid.value
    raise HostAgentUnavailable()


def _read(connection, length, *, unavailable=False):
    pieces = []
    while length:
        chunk = connection.recv(length)
        if not chunk:
            raise HostAgentUnavailable() if unavailable else HostAgentDenied()
        pieces.append(chunk)
        length -= len(chunk)
    return b"".join(pieces)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate wire field.")
        result[key] = value
    return result


def handle_connection(connection: socket.socket, agent, *, allowed_uid: int):
    """One bounded call per connection; caller cannot supply its authority/UID."""
    connection.settimeout(5)
    try:
        if peer_uid(connection) != allowed_uid:
            raise HostAgentDenied()
        length = struct.unpack("!I", _read(connection, 4))[0]
        if not 0 < length <= MAX_FRAME:
            raise HostAgentDenied()
        payload = json.loads(_read(connection, length), object_pairs_hook=_unique_object)
        call = Call.model_validate(payload)
        result = getattr(agent, call.method)(call.command)
        response = {"result": result.model_dump(mode="json")}
    except (HostAgentDenied, SemanticConflict, HostAgentUnavailable) as error:
        response = {"error": {"code": error.code}}
    except ValueError, OSError, RecursionError:
        response = {"error": {"code": "host_agent_denied"}}
    except Exception:
        response = {"error": {"code": "host_agent_unavailable"}}
    encoded = json.dumps(response, separators=(",", ":")).encode()
    if len(encoded) > MAX_FRAME:
        encoded = b'{"error":{"code":"host_agent_unavailable"}}'
    connection.sendall(struct.pack("!I", len(encoded)) + encoded)


@contextmanager
def private_listener(path: Path, *, client_gid: int):
    """Never take over an existing socket. Setup owns the restricted client group.

    Directory owner is the agent UID; no group writes or world access. The socket
    uses the restricted client group and peer UID is independently checked per call.
    """
    if not path.is_absolute() or path.parent.resolve() != path.parent:
        raise HostAgentDenied()
    parent = path.parent.stat()
    if (
        parent.st_uid != os.getuid()
        or parent.st_gid != client_gid
        or stat.S_IMODE(parent.st_mode) & 0o027
    ):
        raise HostAgentDenied()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    identity = None
    try:
        listener.bind(str(path))
        os.chown(path, os.getuid(), client_gid)
        os.chmod(path, 0o660)
        info = path.lstat()
        identity = (info.st_dev, info.st_ino)
        listener.listen(8)
        yield listener
    finally:
        listener.close()
        if identity is not None:
            info = path.lstat()
            if (info.st_dev, info.st_ino) == identity:
                path.unlink()
