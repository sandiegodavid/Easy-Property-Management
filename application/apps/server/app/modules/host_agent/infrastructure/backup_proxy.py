"""Host-side epm-backup-proxy: SO_PEERCRED UID -> prefix-fenced R2 + Cloud KMS proxy (H05.2 / D3).

Zero R2 or Cloud KMS credentials ever enter Operator or Admin containers. Callers are
authenticated exclusively by kernel peer UID mapped through host_inventory.sqlite
(zero Admin DB dependency). Each Operator is strictly confined to
`deployments/<deployment_id>/operators/<operator_id>/...` and Admin to
`deployments/<deployment_id>/control/...`.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import stat
import struct
import threading
import time
from typing import Literal

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.modules.host_agent.infrastructure.unix_transport import _unique_object, peer_uid
from app.modules.hosted_recovery.application.ports import KmsPort, ObjectStorePort
from app.modules.hosted_recovery.domain.models import (
    BackupProxyDenied,
    BackupProxyUnavailable,
    HostedRecoveryError,
    ObjectMetadata,
    RecoveryCryptoError,
    RecoveryIntegrityError,
    canonical_json_bytes,
    validate_kms_key_ref,
    validate_relative_object_key,
)
from app.platform.hosted_schema import validate_schema
from app.platform.schema_resources import HostedStore

MAX_HEADER_BYTES = 16 * 1024
MAX_BODY_BYTES = 2 * 1024 * 1024
PROXY_PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class CallerPrincipal:
    """Authenticated caller identity derived solely from kernel peer UID."""

    uid: int
    scope_kind: Literal["operator", "control"]
    deployment_id: str
    operator_id: str | None
    workspace_id: str | None
    namespace_prefix: str
    allowed_key_refs: frozenset[str]


def _proxy_kms_aad(principal: CallerPrincipal, caller_aad: bytes) -> bytes:
    """Bind the kernel-authenticated namespace_prefix into Cloud KMS AAD."""
    return canonical_json_bytes(
        {
            "deployment_id": principal.deployment_id,
            "scope_kind": principal.scope_kind,
            "operator_id": principal.operator_id,
            "workspace_id": principal.workspace_id,
            "namespace_prefix": principal.namespace_prefix,
            "caller_aad_b64": base64.b64encode(caller_aad).decode("ascii"),
        }
    )


def _validate_list_subprefix(subprefix: str) -> str:
    if subprefix == "":
        return ""
    if not subprefix.endswith("/"):
        raise BackupProxyDenied("List subprefix must be empty or end with '/'.")
    try:
        validate_relative_object_key(subprefix[:-1])
    except ValueError as error:
        raise BackupProxyDenied("Invalid list subprefix.") from error
    return subprefix


class InventoryPeerResolver:
    """Resolve kernel peer UID -> CallerPrincipal from read-only host_inventory.sqlite."""

    def __init__(
        self,
        inventory_path: Path,
        *,
        application_directory: Path,
        expected_deployment_id: str,
        admin_uid: int,
        operator_key_refs: set[str] | frozenset[str],
        control_key_refs: set[str] | frozenset[str],
    ):
        self.inventory_path = inventory_path
        self.application_directory = application_directory
        self.expected_deployment_id = expected_deployment_id
        self.admin_uid = admin_uid
        self.operator_key_refs = frozenset(validate_kms_key_ref(ref) for ref in operator_key_refs)
        self.control_key_refs = frozenset(validate_kms_key_ref(ref) for ref in control_key_refs)
        if not self.operator_key_refs or not self.control_key_refs:
            raise ValueError("operator_key_refs and control_key_refs must be non-empty.")

    def _connect_ro(self) -> sqlite3.Connection:
        if (
            not self.inventory_path.is_absolute()
            or self.inventory_path.resolve() != self.inventory_path
        ):
            raise BackupProxyDenied("Inventory path must be canonical and absolute.")
        raw = sqlite3.connect(
            self.inventory_path.as_uri() + "?mode=ro",
            uri=True,
            isolation_level=None,
        )
        raw.execute("PRAGMA foreign_keys=ON")
        raw.execute("PRAGMA query_only=ON")
        return raw

    def resolve(self, uid: int) -> CallerPrincipal:
        if uid == self.admin_uid:
            return CallerPrincipal(
                uid=uid,
                scope_kind="control",
                deployment_id=self.expected_deployment_id,
                operator_id=None,
                workspace_id=None,
                namespace_prefix=f"deployments/{self.expected_deployment_id}/control/",
                allowed_key_refs=self.control_key_refs,
            )
        engine = create_engine("sqlite://", poolclass=NullPool, creator=self._connect_ro)
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("BEGIN")
                try:
                    validate_schema(
                        connection,
                        HostedStore.HOST_INVENTORY,
                        application_directory=self.application_directory,
                    )
                    identity_rows = list(
                        connection.exec_driver_sql(
                            "SELECT deployment_id FROM host_identity WHERE id = 1"
                        ).mappings()
                    )
                    if (
                        len(identity_rows) != 1
                        or identity_rows[0]["deployment_id"] != self.expected_deployment_id
                    ):
                        raise BackupProxyDenied("Host inventory deployment_id mismatch.")
                    rows = list(
                        connection.exec_driver_sql(
                            "SELECT operator_id, workspace_id FROM operator_principals "
                            "WHERE host_uid = :uid AND retired_at IS NULL",
                            {"uid": uid},
                        ).mappings()
                    )
                finally:
                    connection.rollback()
        except BackupProxyDenied:
            raise
        except Exception as error:
            raise BackupProxyUnavailable("Failed to query host inventory for peer UID.") from error
        finally:
            engine.dispose()

        if len(rows) != 1:
            raise BackupProxyDenied("Caller UID is not an active registered operator principal.")
        operator_id = str(rows[0]["operator_id"])
        workspace_id = str(rows[0]["workspace_id"])
        return CallerPrincipal(
            uid=uid,
            scope_kind="operator",
            deployment_id=self.expected_deployment_id,
            operator_id=operator_id,
            workspace_id=workspace_id,
            namespace_prefix=f"deployments/{self.expected_deployment_id}/operators/{operator_id}/",
            allowed_key_refs=self.operator_key_refs,
        )


class BackupProxyHandler:
    """Dispatches prefix-fenced object and KMS operations for a resolved CallerPrincipal."""

    def __init__(
        self,
        *,
        object_store: ObjectStorePort,
        kms: KmsPort,
        peer_resolver: Callable[[int], CallerPrincipal],
    ):
        self.object_store = object_store
        self.kms = kms
        self.peer_resolver = peer_resolver

    def _full_key(self, principal: CallerPrincipal, relative_key: object) -> str:
        if not isinstance(relative_key, str):
            raise BackupProxyDenied("Object key must be a string.")
        try:
            validated = validate_relative_object_key(relative_key)
        except ValueError as error:
            raise BackupProxyDenied("Invalid relative object key.") from error
        return principal.namespace_prefix + validated

    def _require_allowed_key_ref(self, principal: CallerPrincipal, key_ref: object) -> str:
        if not isinstance(key_ref, str):
            raise BackupProxyDenied("KMS key_ref must be a string.")
        try:
            validated = validate_kms_key_ref(key_ref)
        except ValueError as error:
            raise BackupProxyDenied("Invalid KMS key_ref.") from error
        if validated not in principal.allowed_key_refs:
            raise BackupProxyDenied("KMS key_ref is not authorized for caller scope.")
        return validated

    def dispatch(
        self,
        caller_uid: int,
        header: dict[str, object],
        body: bytes,
    ) -> tuple[dict[str, object], bytes]:
        principal = self.peer_resolver(caller_uid)
        if header.get("version") != PROXY_PROTOCOL_VERSION:
            raise BackupProxyDenied("Unsupported backup proxy protocol version.")
        op = header.get("op")
        if op == "put_object":
            full_key = self._full_key(principal, header.get("key"))
            sha256_hex = hashlib.sha256(body).hexdigest()
            meta = self.object_store.put_object(full_key, body, sha256_hex=sha256_hex)
            return {"ok": True, "meta": meta.model_dump(mode="json")}, b""
        if op == "head_object":
            if body:
                raise BackupProxyDenied("head_object does not accept a body.")
            full_key = self._full_key(principal, header.get("key"))
            meta = self.object_store.head_object(full_key)
            return {"ok": True, "meta": meta.model_dump(mode="json")}, b""
        if op == "get_object":
            if body:
                raise BackupProxyDenied("get_object does not accept a body.")
            full_key = self._full_key(principal, header.get("key"))
            data, meta = self.object_store.get_object(full_key, max_bytes=MAX_BODY_BYTES)
            if len(data) > MAX_BODY_BYTES:
                raise BackupProxyUnavailable("Object exceeds maximum proxy frame size.")
            return {"ok": True, "meta": meta.model_dump(mode="json")}, data
        if op == "delete_object":
            if body:
                raise BackupProxyDenied("delete_object does not accept a body.")
            relative_key = header.get("key")
            full_key = self._full_key(principal, relative_key)
            self.object_store.delete_object(full_key)
            return {"ok": True, "deleted": True}, b""
        if op == "list_objects":
            if body:
                raise BackupProxyDenied("list_objects does not accept a body.")
            raw_sub = header.get("subprefix", "")
            if not isinstance(raw_sub, str):
                raise BackupProxyDenied("subprefix must be a string.")
            subprefix = _validate_list_subprefix(raw_sub)
            raw_max = header.get("max_keys", 1000)
            if (
                not isinstance(raw_max, int)
                or isinstance(raw_max, bool)
                or not 1 <= raw_max <= 1000
            ):
                raise BackupProxyDenied("max_keys must be an integer between 1 and 1000.")
            raw_token = header.get("continuation_token")
            if raw_token is not None and not isinstance(raw_token, str):
                raise BackupProxyDenied("continuation_token must be a string or null.")
            full_prefix = principal.namespace_prefix + subprefix
            full_keys, next_token = self.object_store.list_objects_page(
                full_prefix, max_keys=raw_max, continuation_token=raw_token
            )
            relative_keys: list[str] = []
            for key in full_keys:
                if not key.startswith(principal.namespace_prefix):
                    raise BackupProxyDenied("Storage backend returned key outside caller prefix.")
                relative_keys.append(key[len(principal.namespace_prefix) :])
            keys_body = json.dumps({"keys": relative_keys}, separators=(",", ":")).encode("utf-8")
            if len(keys_body) > MAX_BODY_BYTES:
                raise BackupProxyUnavailable("Object listing exceeds maximum proxy frame size.")
            return {"ok": True, "next_token": next_token}, keys_body
        if op in {"kms_wrap", "kms_unwrap"}:
            key_ref = self._require_allowed_key_ref(principal, header.get("key_ref"))
            raw_aad = header.get("aad_b64")
            if not isinstance(raw_aad, str):
                raise BackupProxyDenied("aad_b64 must be a base64 string.")
            try:
                caller_aad = base64.b64decode(raw_aad.encode("ascii"), validate=True)
            except ValueError as error:
                raise BackupProxyDenied("Invalid aad_b64 encoding.") from error
            scoped_aad = _proxy_kms_aad(principal, caller_aad)
            if op == "kms_wrap":
                wrapped = self.kms.wrap_dek(key_ref, body, aad=scoped_aad)
                return {"ok": True}, wrapped
            unwrapped = self.kms.unwrap_dek(key_ref, body, aad=scoped_aad)
            return {"ok": True}, unwrapped
        raise BackupProxyDenied("Unknown backup proxy operation.")


def _recv_exact(connection: socket.socket, length: int, *, deadline: float | None = None) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        if deadline is not None:
            left = deadline - time.monotonic()
            if left <= 0:
                raise BackupProxyUnavailable("Backup proxy request exceeded total deadline.")
            connection.settimeout(left)
        piece = connection.recv(remaining)
        if not piece:
            raise BackupProxyUnavailable("Unexpected EOF on backup proxy socket.")
        chunks.append(piece)
        remaining -= len(piece)
    return b"".join(chunks)


def _send_frame(connection: socket.socket, header: dict[str, object], body: bytes) -> None:
    encoded_header = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(encoded_header) > MAX_HEADER_BYTES or len(body) > MAX_BODY_BYTES:
        raise BackupProxyUnavailable("Backup proxy frame exceeds configured size limits.")
    connection.sendall(
        struct.pack("!I", len(encoded_header))
        + encoded_header
        + struct.pack("!I", len(body))
        + body
    )


def _recv_frame(
    connection: socket.socket, *, deadline: float | None = None
) -> tuple[dict[str, object], bytes]:
    header_len = struct.unpack("!I", _recv_exact(connection, 4, deadline=deadline))[0]
    if not 1 <= header_len <= MAX_HEADER_BYTES:
        raise BackupProxyDenied("Backup proxy header length out of bounds.")
    header_raw = _recv_exact(connection, header_len, deadline=deadline)
    try:
        header = json.loads(header_raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, ValueError) as error:
        raise BackupProxyDenied("Malformed backup proxy header JSON.") from error
    if not isinstance(header, dict):
        raise BackupProxyDenied("Backup proxy header must be a JSON object.")
    body_len = struct.unpack("!I", _recv_exact(connection, 4, deadline=deadline))[0]
    if body_len > MAX_BODY_BYTES:
        raise BackupProxyDenied("Backup proxy body length out of bounds.")
    body = _recv_exact(connection, body_len, deadline=deadline) if body_len else b""
    return header, body


def handle_proxy_connection(
    connection: socket.socket,
    handler: BackupProxyHandler,
    *,
    timeout_seconds: float = 15.0,
) -> None:
    """Serve one bounded request per Unix socket connection after peer_uid check."""
    deadline = time.monotonic() + timeout_seconds
    connection.settimeout(timeout_seconds)
    try:
        caller_uid = peer_uid(connection)
        header, body = _recv_frame(connection, deadline=deadline)
        response_header, response_body = handler.dispatch(caller_uid, header, body)
    except HostedRecoveryError as error:
        response_header, response_body = {"ok": False, "error": {"code": error.code}}, b""
    except Exception:
        response_header, response_body = (
            {
                "ok": False,
                "error": {"code": BackupProxyUnavailable.code},
            },
            b"",
        )
    try:
        _send_frame(connection, response_header, response_body)
    except HostedRecoveryError as error:
        try:
            _send_frame(connection, {"ok": False, "error": {"code": error.code}}, b"")
        except OSError:
            pass
    except OSError:
        pass


@contextmanager
def backup_proxy_listener(
    socket_path: Path,
    *,
    client_gid: int | None = None,
    socket_mode: int = 0o660,
):
    """Bind a fresh private Unix socket for epm-backup-proxy; never take over an existing socket."""
    if not socket_path.is_absolute() or socket_path.parent.resolve() != socket_path.parent:
        raise BackupProxyDenied("Backup proxy socket path must be canonical and absolute.")
    parent = socket_path.parent.stat()
    if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o027:
        raise BackupProxyDenied("Backup proxy socket directory has unsafe ownership or mode.")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    identity: tuple[int, int] | None = None
    try:
        listener.bind(str(socket_path))
        if client_gid is not None:
            os.chown(socket_path, os.getuid(), client_gid)
        os.chmod(socket_path, socket_mode)
        info = socket_path.lstat()
        identity = (info.st_dev, info.st_ino)
        listener.listen(16)
        yield listener
    finally:
        listener.close()
        if identity is not None and socket_path.exists():
            info = socket_path.lstat()
            if (info.st_dev, info.st_ino) == identity:
                socket_path.unlink()


class BackupProxyServer:
    """Threaded Unix socket server for epm-backup-proxy with bounded queue & per-UID cap."""

    def __init__(
        self,
        listener: socket.socket,
        handler: BackupProxyHandler,
        *,
        max_workers: int = 8,
        max_queued: int = 32,
        max_per_uid: int = 2,
    ):
        self._listener = listener
        self._handler = handler
        self._stop = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="backup-proxy")
        self._queue_slots = threading.BoundedSemaphore(max_queued)
        self._uid_lock = threading.Lock()
        self._uid_inflight: dict[int, int] = {}
        self._max_per_uid = max_per_uid
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._listener.settimeout(0.2)
        self._thread = threading.Thread(target=self._serve_loop, daemon=True)
        self._thread.start()

    def _serve_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            if not self._queue_slots.acquire(blocking=False):
                try:
                    _send_frame(
                        conn,
                        {"ok": False, "error": {"code": BackupProxyUnavailable.code}},
                        b"",
                    )
                except OSError:
                    pass
                finally:
                    conn.close()
                continue
            self._pool.submit(self._handle_and_close, conn)

    def _handle_and_close(self, conn: socket.socket) -> None:
        uid: int | None = None
        acquired_uid = False
        try:
            uid = peer_uid(conn)
            with self._uid_lock:
                current = self._uid_inflight.get(uid, 0)
                if current >= self._max_per_uid:
                    try:
                        _send_frame(
                            conn,
                            {"ok": False, "error": {"code": BackupProxyUnavailable.code}},
                            b"",
                        )
                    except OSError:
                        pass
                    return
                self._uid_inflight[uid] = current + 1
                acquired_uid = True
            handle_proxy_connection(conn, self._handler)
        except Exception:
            pass
        finally:
            if acquired_uid and uid is not None:
                with self._uid_lock:
                    remaining = self._uid_inflight.get(uid, 1) - 1
                    if remaining <= 0:
                        self._uid_inflight.pop(uid, None)
                    else:
                        self._uid_inflight[uid] = remaining
            self._queue_slots.release()
            conn.close()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._pool.shutdown(wait=True)


class UnixBackupProxyClient:
    """Container-side BackupTransport client talking to epm-backup-proxy over AF_UNIX."""

    def __init__(
        self,
        socket_path: Path,
        *,
        expected_proxy_uid: int,
        timeout_seconds: float = 15.0,
    ):
        if not socket_path.is_absolute() or socket_path.parent.resolve() != socket_path.parent:
            raise BackupProxyDenied("Backup proxy socket path must be canonical and absolute.")
        self.socket_path = socket_path
        self.expected_proxy_uid = expected_proxy_uid
        self.timeout_seconds = timeout_seconds

    def _request(
        self,
        header: dict[str, object],
        body: bytes = b"",
    ) -> tuple[dict[str, object], bytes]:
        payload_header = {"version": PROXY_PROTOCOL_VERSION, **header}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(self.timeout_seconds)
                conn.connect(str(self.socket_path))
                if peer_uid(conn) != self.expected_proxy_uid:
                    raise BackupProxyDenied(
                        "Backup proxy peer UID does not match expected host UID."
                    )
                _send_frame(conn, payload_header, body)
                resp_header, resp_body = _recv_frame(conn)
        except HostedRecoveryError:
            raise
        except OSError as error:
            raise BackupProxyUnavailable("Backup proxy socket is unreachable.") from error

        if resp_header.get("ok") is True:
            return resp_header, resp_body
        err = resp_header.get("error")
        code = err.get("code") if isinstance(err, dict) else None
        if code == BackupProxyDenied.code:
            raise BackupProxyDenied("Backup proxy denied request.")
        if code == RecoveryCryptoError.code:
            raise RecoveryCryptoError("Backup proxy cryptographic operation failed.")
        if code == RecoveryIntegrityError.code:
            raise RecoveryIntegrityError("Backup proxy integrity check failed.")
        raise BackupProxyUnavailable("Backup proxy reported unavailability.")

    def put_object(self, relative_key: str, data: bytes) -> ObjectMetadata:
        key = validate_relative_object_key(relative_key)
        resp, _ = self._request({"op": "put_object", "key": key}, data)
        return ObjectMetadata.model_validate(resp["meta"])

    def head_object(self, relative_key: str) -> ObjectMetadata:
        key = validate_relative_object_key(relative_key)
        resp, _ = self._request({"op": "head_object", "key": key})
        return ObjectMetadata.model_validate(resp["meta"])

    def get_object(self, relative_key: str) -> tuple[bytes, ObjectMetadata]:
        key = validate_relative_object_key(relative_key)
        resp, body = self._request({"op": "get_object", "key": key})
        return body, ObjectMetadata.model_validate(resp["meta"])

    def delete_object(self, relative_key: str) -> None:
        key = validate_relative_object_key(relative_key)
        self._request({"op": "delete_object", "key": key})

    def list_objects_page(
        self,
        subprefix: str = "",
        *,
        max_keys: int = 1000,
        continuation_token: str | None = None,
    ) -> tuple[list[str], str | None]:
        validated = _validate_list_subprefix(subprefix)
        header: dict[str, object] = {
            "op": "list_objects",
            "subprefix": validated,
            "max_keys": max_keys,
        }
        if continuation_token is not None:
            header["continuation_token"] = continuation_token
        resp, body = self._request(header)
        if body:
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as error:
                raise BackupProxyUnavailable("Backup proxy returned malformed key body.") from error
            raw_keys = payload.get("keys") if isinstance(payload, dict) else None
        else:
            raw_keys = resp.get("keys")
        if not isinstance(raw_keys, list) or not all(isinstance(item, str) for item in raw_keys):
            raise BackupProxyUnavailable("Backup proxy returned malformed key list.")
        raw_next = resp.get("next_token")
        next_token = raw_next if isinstance(raw_next, str) else None
        return raw_keys, next_token

    def list_objects(self, subprefix: str = "", *, max_keys: int = 1000) -> list[str]:
        all_keys: list[str] = []
        token: str | None = None
        while True:
            page, next_token = self.list_objects_page(
                subprefix, max_keys=max_keys, continuation_token=token
            )
            all_keys.extend(page)
            if not next_token:
                break
            token = next_token
        return all_keys

    def kms_wrap(self, key_ref: str, plaintext_dek: bytes, *, aad: bytes) -> bytes:
        validated = validate_kms_key_ref(key_ref)
        _, body = self._request(
            {
                "op": "kms_wrap",
                "key_ref": validated,
                "aad_b64": base64.b64encode(aad).decode("ascii"),
            },
            plaintext_dek,
        )
        return body

    def kms_unwrap(self, key_ref: str, wrapped_dek: bytes, *, aad: bytes) -> bytes:
        validated = validate_kms_key_ref(key_ref)
        _, body = self._request(
            {
                "op": "kms_unwrap",
                "key_ref": validated,
                "aad_b64": base64.b64encode(aad).decode("ascii"),
            },
            wrapped_dek,
        )
        return body
