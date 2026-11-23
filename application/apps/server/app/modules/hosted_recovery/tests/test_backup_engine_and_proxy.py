"""Component proof tests for H05.2: chunked AEAD backup engine, KMS/R2, and epm-backup-proxy."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from urllib.error import HTTPError, URLError

import pytest

from app.modules.host_agent.infrastructure.backup_proxy import (
    BackupProxyHandler,
    BackupProxyServer,
    CallerPrincipal,
    InventoryPeerResolver,
    UnixBackupProxyClient,
    backup_proxy_listener,
)
from app.modules.hosted_recovery.domain.models import (
    BackupProxyDenied,
    BackupProxyUnavailable,
    EnvelopeContext,
    ObjectMetadata,
    RecoveryCryptoError,
    RecoveryIntegrityError,
    validate_kms_key_ref,
)
from app.modules.hosted_recovery.infrastructure.engine import (
    ChunkedAeadBackupEngine,
    DatabaseInput,
    RetainedFileInput,
)
from app.modules.hosted_recovery.infrastructure.kms_provider import (
    CloudKmsEnvelopeProvider,
    LocalAesKmsProvider,
)
from app.modules.hosted_recovery.infrastructure.r2_store import (
    LocalDirectoryObjectStore,
    R2ObjectStore,
    validate_r2_endpoint,
)
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore

APP_DIR = Path(__file__).resolve().parents[6]
HOST_ID = "00000000-0000-4000-8000-000000000001"
DEPLOYMENT_ID = "00000000-0000-4000-8000-000000000002"
OP_A = "00000000-0000-4000-8000-000000000011"
WS_A = "00000000-0000-4000-8000-000000000012"
OP_B = "00000000-0000-4000-8000-000000000021"
WS_B = "00000000-0000-4000-8000-000000000022"
OP_RETIRED = "00000000-0000-4000-8000-000000000031"
WS_RETIRED = "00000000-0000-4000-8000-000000000032"
KEY_OP_V1 = (
    "projects/epm-demo/locations/us-west1/keyRings/epm-hosted/"
    "cryptoKeys/operator-backup/cryptoKeyVersions/1"
)
KEY_OP_V2 = (
    "projects/epm-demo/locations/us-west1/keyRings/epm-hosted/"
    "cryptoKeys/operator-backup/cryptoKeyVersions/2"
)
KEY_CTRL_V1 = (
    "projects/epm-demo/locations/us-west1/keyRings/epm-hosted/"
    "cryptoKeys/control-backup/cryptoKeyVersions/1"
)


class _DirectProxyTransport:
    """In-process BackupTransport bound to a fixed kernel UID for fast deterministic tests."""

    def __init__(self, handler: BackupProxyHandler, caller_uid: int):
        self._handler = handler
        self._uid = caller_uid

    def _call(
        self, header: dict[str, object], body: bytes = b""
    ) -> tuple[dict[str, object], bytes]:
        return self._handler.dispatch(self._uid, {"version": 1, **header}, body)

    def put_object(self, relative_key: str, data: bytes) -> ObjectMetadata:
        resp, _ = self._call({"op": "put_object", "key": relative_key}, data)
        return ObjectMetadata.model_validate(resp["meta"])

    def head_object(self, relative_key: str) -> ObjectMetadata:
        resp, _ = self._call({"op": "head_object", "key": relative_key})
        return ObjectMetadata.model_validate(resp["meta"])

    def get_object(self, relative_key: str) -> tuple[bytes, ObjectMetadata]:
        resp, body = self._call({"op": "get_object", "key": relative_key})
        return body, ObjectMetadata.model_validate(resp["meta"])

    def delete_object(self, relative_key: str) -> None:
        self._call({"op": "delete_object", "key": relative_key})

    def list_objects_page(
        self, subprefix: str = "", *, max_keys: int = 1000, continuation_token: str | None = None
    ) -> tuple[list[str], str | None]:
        req: dict[str, object] = {
            "op": "list_objects",
            "subprefix": subprefix,
            "max_keys": max_keys,
        }
        if continuation_token is not None:
            req["continuation_token"] = continuation_token
        resp, body = self._call(req)
        keys = json.loads(body.decode("utf-8"))["keys"] if body else resp["keys"]
        return list(keys), resp.get("next_token")

    def list_objects(self, subprefix: str = "", *, max_keys: int = 1000) -> list[str]:
        keys, _ = self.list_objects_page(subprefix, max_keys=max_keys)
        return keys

    def kms_wrap(self, key_ref: str, plaintext_dek: bytes, *, aad: bytes) -> bytes:
        _, body = self._call(
            {
                "op": "kms_wrap",
                "key_ref": key_ref,
                "aad_b64": base64.b64encode(aad).decode("ascii"),
            },
            plaintext_dek,
        )
        return body

    def kms_unwrap(self, key_ref: str, wrapped_dek: bytes, *, aad: bytes) -> bytes:
        _, body = self._call(
            {
                "op": "kms_unwrap",
                "key_ref": key_ref,
                "aad_b64": base64.b64encode(aad).decode("ascii"),
            },
            wrapped_dek,
        )
        return body


def _create_inventory_db(tmp_path: Path) -> Path:
    inv_dir = tmp_path / "inventory"
    inv_dir.mkdir(mode=0o700)
    db_path = inv_dir / "host_inventory.sqlite"
    initialize_store(HostedStore.HOST_INVENTORY, db_path, application_directory=APP_DIR)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT INTO host_identity "
            "(id, host_id, deployment_id, filesystem_identity, agent_contract_version, created_at) "
            "VALUES (1, ?, ?, 'ext4:dev1', 'v1', 1700000000000)",
            (HOST_ID, DEPLOYMENT_ID),
        )
        conn.execute(
            "INSERT INTO operator_principals "
            "(operator_id, workspace_id, host_uid, host_gid, assigned_at, retired_at, cleanup_verified_at, revision) "
            "VALUES (?, ?, 20001, 20001, 1700000000000, NULL, NULL, 1)",
            (OP_A, WS_A),
        )
        conn.execute(
            "INSERT INTO operator_principals "
            "(operator_id, workspace_id, host_uid, host_gid, assigned_at, retired_at, cleanup_verified_at, revision) "
            "VALUES (?, ?, 20002, 20002, 1700000000000, NULL, NULL, 1)",
            (OP_B, WS_B),
        )
        conn.execute(
            "INSERT INTO operator_principals "
            "(operator_id, workspace_id, host_uid, host_gid, assigned_at, retired_at, cleanup_verified_at, revision) "
            "VALUES (?, ?, 20003, 20003, 1700000000000, 1700000001000, NULL, 2)",
            (OP_RETIRED, WS_RETIRED),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _make_proxy_stack(tmp_path: Path):
    inv_path = _create_inventory_db(tmp_path)
    store = LocalDirectoryObjectStore(tmp_path / "r2-bucket")
    kms = LocalAesKmsProvider(
        {
            KEY_OP_V1: hashlib.sha256(b"op-kek-v1").digest(),
            KEY_OP_V2: hashlib.sha256(b"op-kek-v2").digest(),
            KEY_CTRL_V1: hashlib.sha256(b"ctrl-kek-v1").digest(),
        }
    )
    resolver = InventoryPeerResolver(
        inv_path,
        application_directory=APP_DIR,
        expected_deployment_id=DEPLOYMENT_ID,
        admin_uid=10001,
        operator_key_refs={KEY_OP_V1, KEY_OP_V2},
        control_key_refs={KEY_CTRL_V1},
    )
    handler = BackupProxyHandler(object_store=store, kms=kms, peer_resolver=resolver.resolve)
    return store, kms, resolver, handler


def _context(
    *,
    point_id: str,
    operator_id: str = OP_A,
    workspace_id: str = WS_A,
    key_ref: str = KEY_OP_V1,
    scope_kind: str = "operator",
) -> EnvelopeContext:
    return EnvelopeContext(
        deployment_id=DEPLOYMENT_ID,
        scope_kind=scope_kind,
        operator_id=operator_id if scope_kind == "operator" else None,
        workspace_id=workspace_id if scope_kind == "operator" else None,
        point_id=point_id,
        schema_revisions={"business": "20260401_0001", "access": "access_0001_initial"},
        key_ref=key_ref,
    )


def test_dedup_readback_restore_and_reference_safe_pruning(tmp_path: Path):
    store, _, _, handler = _make_proxy_stack(tmp_path)
    transport_a = _DirectProxyTransport(handler, caller_uid=20001)
    engine = ChunkedAeadBackupEngine(transport_a, chunk_size=4096)

    staging = tmp_path / "staging"
    staging.mkdir()
    db_file = staging / "property-management.sqlite"
    # 3 full 4 KiB chunks so partial mutation only dirties 1 chunk.
    db_v1 = (b"A" * 4096) + (b"B" * 4096) + (b"C" * 4096)
    db_file.write_bytes(db_v1)
    doc_1 = staging / "lease-1.pdf"
    doc_1.write_bytes(b"LEASE-ONE-" * 600)

    p1 = engine.create_point(
        context=_context(point_id="pt_001"),
        captured_at=1700000010000,
        business_revision="rev-1",
        files_generation="fg-1",
        source_generation=1,
        release_ref="rel-1",
        databases=[DatabaseInput("property-management.sqlite", db_file)],
        files=[RetainedFileInput("leases/lease-1.pdf", doc_1)],
        full_readback=True,
    )
    assert p1.uploaded_chunks == 5  # 3 db chunks + 2 file chunks
    assert p1.deduplicated_chunks == 0
    assert p1.verified_chunks == 5

    # Point 2 with identical content: 0 chunks uploaded, 100% deduplicated.
    p2 = engine.create_point(
        context=_context(point_id="pt_002"),
        captured_at=1700000020000,
        business_revision="rev-1",
        files_generation="fg-1",
        source_generation=1,
        release_ref="rel-1",
        databases=[DatabaseInput("property-management.sqlite", db_file)],
        files=[RetainedFileInput("leases/lease-1.pdf", doc_1)],
        existing_wrapped_dek_b64=p1.wrapped_dek_b64,
        existing_key_ref=p1.key_ref,
        full_readback=True,
    )
    assert p2.uploaded_chunks == 0
    assert p2.deduplicated_chunks == 5
    assert p2.verified_chunks == 5

    # Point 3 mutates only the middle 4 KiB DB chunk and adds a second retained file.
    db_v3 = (b"A" * 4096) + (b"X" * 4096) + (b"C" * 4096)
    db_file.write_bytes(db_v3)
    doc_2 = staging / "receipt-2.pdf"
    doc_2.write_bytes(b"RECEIPT-TWO-" * 100)
    p3 = engine.create_point(
        context=_context(point_id="pt_003"),
        captured_at=1700000030000,
        business_revision="rev-2",
        files_generation="fg-2",
        source_generation=1,
        release_ref="rel-1",
        databases=[DatabaseInput("property-management.sqlite", db_file)],
        files=[
            RetainedFileInput("leases/lease-1.pdf", doc_1),
            RetainedFileInput("receipts/receipt-2.pdf", doc_2),
        ],
        existing_wrapped_dek_b64=p1.wrapped_dek_b64,
        existing_key_ref=p1.key_ref,
    )
    assert p3.uploaded_chunks == 2  # 1 mutated DB chunk + 1 new file chunk
    assert p3.deduplicated_chunks == 4  # 2 unchanged DB chunks + 2 unchanged lease-1 chunks
    assert p3.verified_chunks == 2

    # Reference-safe prune keeping only p3: deletes ONLY the old 'B'*4096 chunk from p1/p2.
    prune = engine.prune_unreferenced_chunks(
        retained_manifest_refs=[p3.manifest_ref],
        expected_deployment_id=DEPLOYMENT_ID,
        expected_scope_kind="operator",
        expected_operator_id=OP_A,
        expected_workspace_id=WS_A,
    )
    assert len(prune.deleted_chunks) == 1
    assert prune.retained_chunks == 6

    # Restoring p3 produces byte-for-byte identical DB and retained files.
    restore_dir = tmp_path / "restored-p3"
    restore_dir.mkdir(mode=0o700)
    restored = engine.restore_point(
        manifest_ref=p3.manifest_ref,
        expected_deployment_id=DEPLOYMENT_ID,
        expected_scope_kind="operator",
        expected_operator_id=OP_A,
        expected_workspace_id=WS_A,
        expected_manifest_sha256=p3.manifest_sha256,
        destination_dir=restore_dir,
    )
    assert restored.database_files == ["property-management.sqlite"]
    assert restored.restored_files == ["leases/lease-1.pdf", "receipts/receipt-2.pdf"]
    assert (restore_dir / "property-management.sqlite").read_bytes() == db_v3
    assert (restore_dir / "files/leases/lease-1.pdf").read_bytes() == doc_1.read_bytes()
    assert (restore_dir / "files/receipts/receipt-2.pdf").read_bytes() == doc_2.read_bytes()
    # Confirm objects live strictly under Operator A's prefix in R2.
    all_keys = store.list_objects(f"deployments/{DEPLOYMENT_ID}/")
    assert all(key.startswith(f"deployments/{DEPLOYMENT_ID}/operators/{OP_A}/") for key in all_keys)


def test_key_rotation_preserves_old_points_and_namespaces_new_chunks(tmp_path: Path):
    _, _, _, handler = _make_proxy_stack(tmp_path)
    engine = ChunkedAeadBackupEngine(_DirectProxyTransport(handler, 20001), chunk_size=4096)
    db_file = tmp_path / "db.sqlite"
    db_file.write_bytes(b"Z" * 5000)

    p1 = engine.create_point(
        context=_context(point_id="pt_rot_1", key_ref=KEY_OP_V1),
        captured_at=1700000010000,
        business_revision="rev-1",
        files_generation="fg-1",
        source_generation=1,
        release_ref="rel-1",
        databases=[DatabaseInput("property-management.sqlite", db_file)],
    )
    p2 = engine.create_point(
        context=_context(point_id="pt_rot_2", key_ref=KEY_OP_V2),
        captured_at=1700000020000,
        business_revision="rev-1",
        files_generation="fg-1",
        source_generation=1,
        release_ref="rel-1",
        databases=[DatabaseInput("property-management.sqlite", db_file)],
        existing_wrapped_dek_b64=p1.wrapped_dek_b64,
        existing_key_ref=p1.key_ref,
    )
    assert p2.uploaded_chunks == 2  # Fresh DEK + key fingerprint under v2
    assert p2.wrapped_dek_b64 != p1.wrapped_dek_b64

    for point, folder in ((p1, "out1"), (p2, "out2")):
        dest = tmp_path / folder
        dest.mkdir(mode=0o700)
        engine.restore_point(
            manifest_ref=point.manifest_ref,
            expected_deployment_id=DEPLOYMENT_ID,
            expected_scope_kind="operator",
            expected_operator_id=OP_A,
            expected_workspace_id=WS_A,
            destination_dir=dest,
        )
        assert (dest / "property-management.sqlite").read_bytes() == b"Z" * 5000


def test_tamper_corruption_and_missing_chunk_rejected(tmp_path: Path):
    store, _, _, handler = _make_proxy_stack(tmp_path)
    transport_a = _DirectProxyTransport(handler, 20001)
    engine = ChunkedAeadBackupEngine(transport_a, chunk_size=4096)

    db_file = tmp_path / "db.sqlite"
    db_file.write_bytes(b"SENSITIVE-DB-" * 500)
    point = engine.create_point(
        context=_context(point_id="pt_tamper"),
        captured_at=1700000010000,
        business_revision="rev-1",
        files_generation="fg-1",
        source_generation=1,
        release_ref="rel-1",
        databases=[DatabaseInput("property-management.sqlite", db_file)],
    )

    prefix = f"deployments/{DEPLOYMENT_ID}/operators/{OP_A}/"
    chunk_keys = store.list_objects(prefix + "chunks/")
    assert chunk_keys
    chunk_path = store.root / chunk_keys[0]
    original_chunk = chunk_path.read_bytes()

    # 1. Bit-flip in chunk ciphertext -> rejected.
    corrupted = bytearray(original_chunk)
    corrupted[-1] ^= 0xFF
    chunk_path.write_bytes(bytes(corrupted))
    dest = tmp_path / "restore_corrupt"
    dest.mkdir(mode=0o700)
    with pytest.raises((RecoveryIntegrityError, RecoveryCryptoError)):
        engine.restore_point(
            manifest_ref=point.manifest_ref,
            expected_deployment_id=DEPLOYMENT_ID,
            expected_scope_kind="operator",
            expected_operator_id=OP_A,
            expected_workspace_id=WS_A,
            destination_dir=dest,
        )

    # 2. Missing chunk -> rejected.
    chunk_path.unlink()
    with pytest.raises(RecoveryIntegrityError):
        engine.verify_point(
            manifest_ref=point.manifest_ref,
            expected_context=_context(point_id="pt_tamper"),
            only_object_keys=None,
        )
    chunk_path.write_bytes(original_chunk)

    # 3. Tampered manifest AAD metadata (mutating schema_revisions in envelope) -> AEAD tag fails.
    manifest_path = store.root / (prefix + point.manifest_ref)
    envelope = json.loads(manifest_path.read_text())
    envelope["schema_revisions"]["business"] = "tampered_rev"
    manifest_path.write_text(json.dumps(envelope))
    with pytest.raises(RecoveryCryptoError):
        engine.load_manifest(
            manifest_ref=point.manifest_ref,
            expected_deployment_id=DEPLOYMENT_ID,
            expected_scope_kind="operator",
            expected_operator_id=OP_A,
            expected_workspace_id=WS_A,
        )


def test_proxy_prefix_fencing_uid_isolation_and_cross_operator_kms_denial(tmp_path: Path):
    _, _, _, handler = _make_proxy_stack(tmp_path)
    transport_a = _DirectProxyTransport(handler, caller_uid=20001)
    transport_b = _DirectProxyTransport(handler, caller_uid=20002)
    transport_admin = _DirectProxyTransport(handler, caller_uid=10001)

    # Operator A writes an object and wraps a DEK.
    transport_a.put_object("manifests/pt_a.json.enc", b"operator-a-secret")
    dek_a = os.urandom(32)
    aad_a = _context(point_id="pt_a").kms_aad()
    wrapped_a = transport_a.kms_wrap(KEY_OP_V1, dek_a, aad=aad_a)

    # Operator B cannot see Operator A's object, cannot traverse into Operator A's prefix,
    # and cannot unwrap Operator A's DEK even if it supplies Operator A's exact caller AAD.
    assert transport_b.head_object("manifests/pt_a.json.enc").exists is False
    assert transport_b.list_objects("") == []
    with pytest.raises(BackupProxyDenied):
        transport_b.get_object(f"../{OP_A}/manifests/pt_a.json.enc")
    with pytest.raises(BackupProxyDenied):
        transport_b.get_object("/etc/passwd")
    with pytest.raises(RecoveryCryptoError):
        transport_b.kms_unwrap(KEY_OP_V1, wrapped_a, aad=aad_a)

    # Operator A cannot use Admin's KMS key; Admin cannot use Operator's KMS key.
    with pytest.raises(BackupProxyDenied):
        transport_a.kms_wrap(KEY_CTRL_V1, dek_a, aad=aad_a)
    with pytest.raises(BackupProxyDenied):
        transport_admin.kms_wrap(KEY_OP_V1, dek_a, aad=aad_a)

    # Admin control scope works independently of Operator namespaces.
    transport_admin.put_object("manifests/ctrl_1.json.enc", b"control-manifest")
    assert transport_admin.list_objects("manifests/") == ["manifests/ctrl_1.json.enc"]
    assert transport_a.list_objects("manifests/") == ["manifests/pt_a.json.enc"]

    # Unknown UID and retired operator UID are denied.
    with pytest.raises(BackupProxyDenied):
        handler.dispatch(99999, {"version": 1, "op": "list_objects", "subprefix": ""}, b"")
    with pytest.raises(BackupProxyDenied):
        handler.dispatch(20003, {"version": 1, "op": "list_objects", "subprefix": ""}, b"")


def test_unix_socket_backup_proxy_end_to_end(tmp_path: Path):
    """Real AF_UNIX socket round-trip with SO_PEERCRED / getpeereid verification."""
    my_uid = os.getuid()
    store = LocalDirectoryObjectStore(tmp_path / "r2")
    kms = LocalAesKmsProvider({KEY_OP_V1: hashlib.sha256(b"unix-kek").digest()})

    def resolve_self(uid: int) -> CallerPrincipal:
        if uid != my_uid:
            raise BackupProxyDenied("Unexpected caller UID.")
        return CallerPrincipal(
            uid=uid,
            scope_kind="operator",
            deployment_id=DEPLOYMENT_ID,
            operator_id=OP_A,
            workspace_id=WS_A,
            namespace_prefix=f"deployments/{DEPLOYMENT_ID}/operators/{OP_A}/",
            allowed_key_refs=frozenset({KEY_OP_V1}),
        )

    handler = BackupProxyHandler(object_store=store, kms=kms, peer_resolver=resolve_self)
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="epm-bp-") as short_dir:
        sock_dir = Path(short_dir).resolve()
        os.chmod(sock_dir, 0o700)
        sock_path = sock_dir / "bp.sock"

        with backup_proxy_listener(sock_path, socket_mode=0o600) as listener:
            server = BackupProxyServer(listener, handler, max_workers=2)
            server.start()
            try:
                client = UnixBackupProxyClient(sock_path, expected_proxy_uid=my_uid)
                engine = ChunkedAeadBackupEngine(client, chunk_size=4096)
                db_file = tmp_path / "biz.sqlite"
                db_file.write_bytes(b"UNIX-BACKUP-DATA-" * 400)
                result = engine.create_point(
                    context=_context(point_id="pt_unix_1"),
                    captured_at=1700000010000,
                    business_revision="rev-1",
                    files_generation="fg-1",
                    source_generation=1,
                    release_ref="rel-1",
                    databases=[DatabaseInput("property-management.sqlite", db_file)],
                    full_readback=True,
                )
                assert result.uploaded_chunks == 2
                assert result.verified_chunks == 2

                # Client rejects proxy if expected_proxy_uid does not match kernel peer UID.
                wrong_client = UnixBackupProxyClient(sock_path, expected_proxy_uid=my_uid + 1)
                with pytest.raises(BackupProxyDenied):
                    wrong_client.list_objects("")
            finally:
                server.stop()


def test_r2_object_store_and_cloud_kms_validation_and_protocol():
    # R2 endpoint & bucket validation.
    valid_ep = "https://" + "a" * 32 + ".r2.cloudflarestorage.com"
    assert validate_r2_endpoint(valid_ep) == valid_ep
    with pytest.raises(ValueError):
        validate_r2_endpoint("http://" + "a" * 32 + ".r2.cloudflarestorage.com")
    with pytest.raises(ValueError):
        validate_r2_endpoint("https://example.com")

    # Mocked boto3 client verifies metadata SHA-256 on put/head/get.
    objects: dict[str, tuple[bytes, dict[str, str]]] = {}

    class _FakeS3:
        def put_object(self, *, Bucket, Key, Body, ContentType, Metadata):
            objects[Key] = (Body, dict(Metadata))

        def head_object(self, *, Bucket, Key):
            if Key not in objects:
                err = RuntimeError("NotFound")
                err.response = {
                    "Error": {"Code": "404"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                }
                raise err
            body, meta = objects[Key]
            return {"ContentLength": len(body), "Metadata": meta}

        def get_object(self, *, Bucket, Key):
            body, meta = objects[Key]
            return {"Body": io.BytesIO(body), "Metadata": meta}

        def delete_object(self, *, Bucket, Key):
            objects.pop(Key, None)

        def list_objects_v2(self, *, Bucket, Prefix, MaxKeys, ContinuationToken=None):
            matched = [{"Key": k} for k in sorted(objects) if k.startswith(Prefix)][:MaxKeys]
            return {"Contents": matched, "IsTruncated": False}

    r2 = R2ObjectStore(endpoint_url=valid_ep, bucket="epm-backups", client=_FakeS3())
    payload = b"encrypted-chunk-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    meta = r2.put_object("deployments/d1/operators/op1/chunks/c1.enc", payload, sha256_hex=digest)
    assert meta.sha256 == digest
    assert r2.head_object("deployments/d1/operators/op1/chunks/c1.enc").exists is True
    assert r2.head_object("deployments/d1/operators/op1/chunks/missing.enc").exists is False
    got, got_meta = r2.get_object("deployments/d1/operators/op1/chunks/c1.enc")
    assert got == payload and got_meta.sha256 == digest
    assert r2.list_objects("deployments/d1/operators/op1/") == [
        "deployments/d1/operators/op1/chunks/c1.enc"
    ]

    # Cloud KMS REST client protocol & error mapping.
    assert validate_kms_key_ref(KEY_OP_V1) == KEY_OP_V1
    with pytest.raises(ValueError):
        validate_kms_key_ref("not-a-kms-key")

    seen_urls: list[str] = []

    def _fake_opener(request, timeout):
        seen_urls.append(request.full_url)
        req_body = json.loads(request.data.decode("utf-8"))
        if request.full_url.endswith(":encrypt"):
            return json.dumps({"ciphertext": req_body["plaintext"]}).encode("utf-8")
        return json.dumps({"plaintext": req_body["ciphertext"]}).encode("utf-8")

    kms_client = CloudKmsEnvelopeProvider(token_supplier=lambda: "tok", opener=_fake_opener)
    dek = os.urandom(32)
    wrapped = kms_client.wrap_dek(KEY_OP_V1, dek, aad=b"aad-bytes")
    unwrapped = kms_client.unwrap_dek(KEY_OP_V1, wrapped, aad=b"aad-bytes")
    assert unwrapped == dek
    assert seen_urls[0].endswith(f"/{KEY_OP_V1}:encrypt")
    assert seen_urls[1].endswith("/cryptoKeys/operator-backup:decrypt")

    # HTTP 403 -> RecoveryCryptoError; URLError -> BackupProxyUnavailable.
    def _deny_opener(request, timeout):
        raise HTTPError(request.full_url, 403, "Forbidden", {}, None)

    def _offline_opener(request, timeout):
        raise URLError("network down")

    with pytest.raises(RecoveryCryptoError):
        CloudKmsEnvelopeProvider(token_supplier=lambda: "tok", opener=_deny_opener).wrap_dek(
            KEY_OP_V1, dek, aad=b"aad"
        )
    with pytest.raises(BackupProxyUnavailable):
        CloudKmsEnvelopeProvider(token_supplier=lambda: "tok", opener=_offline_opener).wrap_dek(
            KEY_OP_V1, dek, aad=b"aad"
        )
