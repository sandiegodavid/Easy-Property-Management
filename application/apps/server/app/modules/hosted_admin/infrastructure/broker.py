"""Length-bounded Unix RPC with kernel peer identity, never caller-supplied identity."""

import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import struct
import threading
from contextlib import contextmanager

from pydantic import ValidationError

from app.modules.hosted_admin.application.contracts import AdminError, BrokerRequest, CommandRequest

MAX_FRAME = 16384
MAX_RESPONSE_FRAME = 256 * 1024
MAX_CONNECTIONS = 16
MAX_EFFECTS = 4
MAX_URGENT_EFFECTS = 2


class BoundedUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """No unbounded thread/queue growth; slow effects have a separate lower cap."""

    request_queue_size = MAX_CONNECTIONS

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(0.1)
                send(request, {"error": "admin_broker_busy", "status": 503})
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


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


def receive(connection, maximum=MAX_FRAME):
    size = struct.unpack("!I", read_exact(connection, 4))[0]
    if not 0 < size <= maximum:
        raise AdminError("admin_request_too_large", 413)
    return json.loads(read_exact(connection, size))


def send(connection, value):
    raw = json.dumps(value).encode()
    if len(raw) > MAX_RESPONSE_FRAME:
        raise AdminError("admin_response_too_large", 503)
    connection.sendall(struct.pack("!I", len(raw)) + raw)


def rpc(path, payload):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(30)
        connection.connect(str(path))
        send(connection, payload)
        result = receive(connection, MAX_RESPONSE_FRAME)
    if "error" in result:
        raise AdminError(result["error"], result["status"])
    return result["result"]


class Broker:
    def __init__(
        self,
        authority,
        admin_uid,
        dispatch,
        peer=peer_uid,
        operations=None,
        console=None,
        setup=None,
    ):
        self.console = console
        self.setup = setup
        self.operations = operations
        self.effects = threading.BoundedSemaphore(MAX_EFFECTS)
        self.urgent_effects = threading.BoundedSemaphore(MAX_URGENT_EFFECTS)
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
            with self.lane(uid, payload):
                if uid == 0:
                    result = self._private(payload)
                else:
                    request = BrokerRequest.model_validate(payload)
                    result = self.authority.handle(request, self.dispatch, self.console, self.setup)
            send(connection, {"result": result})
        except AdminError as error:
            send(connection, {"error": error.code, "status": error.status})
        except (ValueError, ValidationError, TypeError) as _error:
            send(connection, {"error": "admin_request_invalid", "status": 400})
        except Exception:
            # Never reflect private paths, provider output, credentials or traceback into RPC.
            send(connection, {"error": "admin_operation_unavailable", "status": 503})

    @contextmanager
    def lane(self, uid, payload):
        """Only known short control reads/fences bypass bounded external effects.

        Classification grants no authority; the existing closed request models,
        peer checks, sessions and owning commands still validate every request.
        Saturated lanes reject rather than occupy control slots waiting in line.
        """
        method = payload.get("method") if isinstance(payload, dict) else None
        command = payload.get("command", {}) if isinstance(payload, dict) else {}
        private = payload.get("request", {}) if isinstance(payload, dict) else {}
        action = command.get("action") if isinstance(command, dict) else None
        private_action = private.get("action") if isinstance(private, dict) else None
        short = (
            (
                uid == 0
                and method in {"bootstrap", "revoke_identity", "restore_identity", "action_grant"}
            )
            or (
                uid != 0
                and method
                in {
                    "login",
                    "session",
                    "logout",
                    "reauthenticate",
                    "lookup",
                    "operation",
                    "operation_list",
                    "cancel",
                    "resume",
                    "console_operation",
                }
            )
            or (
                uid == 0
                and method == "private_operations"
                and private_action in {"operation-status", "resume-grant"}
            )
        )
        urgent = (method == "command" and action in {"disable", "revoke"}) or (
            uid == 0 and method == "private_operations" and private_action == "operation-stop"
        )
        gate = None if short else self.urgent_effects if urgent else self.effects
        if gate is not None and not gate.acquire(blocking=False):
            raise AdminError("admin_broker_busy", 503)
        try:
            yield
        finally:
            if gate is not None:
                gate.release()

    def _private(self, payload):
        if (
            isinstance(payload, dict)
            and set(payload) == {"method", "request"}
            and payload["method"] == "private_operations"
        ):
            if self.operations is None:
                raise AdminError("admin_operation_service_unavailable", 503)
            return self.operations.handle(payload["request"])
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

        with BoundedUnixServer(str(path), Handler) as server:
            os.chown(path, 0, group)
            path.chmod(0o660)
            try:
                server.serve_forever()
            finally:
                path.unlink()
