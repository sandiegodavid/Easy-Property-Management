"""Length-bounded Unix RPC with kernel peer identity, never caller-supplied identity."""

import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import struct

from pydantic import ValidationError

from app.modules.hosted_admin.application.contracts import AdminError, BrokerRequest, CommandRequest

MAX_FRAME = 16384


def peer_uid(connection):
    if hasattr(socket, "SO_PEERCRED"):
        return struct.unpack(
            "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        )[1]
    raise AdminError("admin_peer_platform_unqualified", 503)


def read_exact(connection, size):
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            raise AdminError("admin_transport_incomplete", 400)
        chunks.extend(chunk)
    return bytes(chunks)


def receive(connection):
    size = struct.unpack("!I", read_exact(connection, 4))[0]
    if not 0 < size <= MAX_FRAME:
        raise AdminError("admin_request_too_large", 413)
    return json.loads(read_exact(connection, size))


def send(connection, value):
    raw = json.dumps(value).encode()
    if len(raw) > MAX_FRAME:
        raise AdminError("admin_response_too_large", 503)
    connection.sendall(struct.pack("!I", len(raw)) + raw)


def rpc(path, payload):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(30)
        connection.connect(str(path))
        send(connection, payload)
        result = receive(connection)
    if "error" in result:
        raise AdminError(result["error"], result["status"])
    return result["result"]


class Broker:
    def __init__(self, authority, admin_uid, dispatch, peer=peer_uid):
        if admin_uid == 0:
            raise AdminError("admin_http_must_be_unprivileged", 503)
        self.authority, self.admin_uid, self.dispatch, self.peer = (
            authority,
            admin_uid,
            dispatch,
            peer,
        )

    def handle(self, connection):
        connection.settimeout(5)
        try:
            uid = self.peer(connection)
            if uid not in {0, self.admin_uid}:
                raise AdminError("admin_peer_denied")
            payload = receive(connection)
            if uid == 0:
                result = self._private(payload)
            else:
                request = BrokerRequest.model_validate(payload)
                result = self.authority.handle(request, self.dispatch)
            send(connection, {"result": result})
        except AdminError as error:
            send(connection, {"error": error.code, "status": error.status})
        except (ValueError, ValidationError, TypeError) as _error:
            send(connection, {"error": "admin_request_invalid", "status": 400})
        except Exception:
            # Never reflect private paths, provider output, credentials or traceback into RPC.
            send(connection, {"error": "admin_operation_unavailable", "status": 503})

    def _private(self, payload):
        if payload == {"method": "bootstrap"}:
            return {"credential": self.authority.issue()}
        if payload == {"method": "revoke_identity"}:
            self.authority.revoke_identity()
            return {"revoked": True}
        if payload == {"method": "restore_identity"}:
            self.authority.restore_identity()
            return {"restored": True}
        if (
            isinstance(payload, dict)
            and set(payload) == {"method", "command"}
            and payload["method"] == "action_grant"
        ):
            command = CommandRequest.model_validate(payload["command"])
            return {"credential": self.authority.issue(command.fingerprint())}
        raise AdminError("admin_private_command_invalid", 400)

    def serve(self, path, group):
        path = Path(path)
        # Installation creates this root-controlled group-traversable directory.
        info = path.parent.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != 0
            or info.st_mode & 0o022
            or path.exists()
            or path.is_symlink()
        ):
            raise AdminError("admin_socket_unsafe", 503)
        broker = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                broker.handle(self.request)

        with socketserver.UnixStreamServer(str(path), Handler) as server:
            os.chown(path, 0, group)
            path.chmod(0o660)
            try:
                server.serve_forever()
            finally:
                path.unlink()
