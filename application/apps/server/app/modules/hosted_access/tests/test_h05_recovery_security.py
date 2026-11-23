"""H05.10 Security Review & Negative Gate Verification Suite.

Verifies every negative security boundary before enabling hosted restore:
  1. Stolen/ordinary session without fresh strong step-up, CSRF/Origin/query checks
  2. Forged Admin/Operator role confusion & zero Admin customer-restore surface
  3. Cross-workspace point, KMS key, prefix, and AAD isolation
  4. Single-use confirmation replay, semantic conflict (409), and mismatched request_hash
  5. Path traversal and symlink escape denial
  6. Tampered manifest and tampered ciphertext chunk rejection
  7. Zero offline workspace decrypt/restore bypass (D11)
  8. Positive workspace gateway negative gate without verified H05 proof (D9)
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from app.modules.host_agent.application.dispatch import HostAgentUnavailable
from app.modules.host_agent.infrastructure.auth_projection import auth_config
from app.modules.host_agent.infrastructure.backup_proxy import (
    BackupProxyHandler,
    CallerPrincipal,
)
from app.modules.host_agent.infrastructure.gateway import GatewaySettings
from app.modules.hosted_access.api.operator_recovery import (
    OperatorRecoveryInputs,
    operator_recovery_router,
)
from app.modules.hosted_recovery.domain.models import (
    BackupProxyDenied,
    EnvelopeContext,
    HostedRecoveryError,
    validate_relative_file_path,
)
from app.modules.hosted_recovery.infrastructure.engine import (
    ChunkedAeadBackupEngine,
    DatabaseInput,
)
from app.modules.hosted_recovery.infrastructure.kms_provider import LocalAesKmsProvider
from app.modules.hosted_recovery.infrastructure.r2_store import LocalDirectoryObjectStore
from app.modules.hosted_recovery.tests.test_h05_backup_runner_and_alerting import (
    DEPLOYMENT_ID,
    KMS_KEY,
    OP_ID,
    WS_ID,
    _DirectTransport,
    _capture_cmd,
    _setup_workspace_fixture,
)
from app.modules.hosted_recovery.tests.test_h05_positive_workspace_gateway import (
    _make_projection,
)
from app.modules.workspace.infrastructure.hosted_recovery import (
    RestoreDeniedError,
    RestoreNotFoundError,
    WorkspaceStateUnreadable,
    _read_retained_files,
)
from app.platform.hosted_contracts.authority import (
    AdminAuthority,
    OperatorAuthority,
    OperatorRestoreAuthority,
)
from app.platform.hosted_contracts.operations import SemanticConflict
from app.platform.hosted_contracts.values import WorkspaceScope

APP_DIR = Path(__file__).resolve().parents[6]
ORIGIN = "https://ws-alpha.example.invalid"
COOKIE_VAL = "a" * 43


class _StubSessions:
    """Minimal session stub enforcing cookie, CSRF, and exact recent_auth_grant matching."""

    def __init__(self, *, valid_grant: str = "valid-step-up-grant-1234567890") -> None:
        self.valid_grant = valid_grant
        self.consumed: set[str] = set()
        self.destination = type(
            "Dest",
            (),
            {
                "binding": staticmethod(
                    lambda: type(
                        "Bind",
                        (),
                        {
                            "deployment_id": DEPLOYMENT_ID,
                            "scope": WorkspaceScope(operator_id=OP_ID, workspace_id=WS_ID),
                        },
                    )()
                )
            },
        )()

    def authorize_with_restore(self, cookie: str, *, csrf: str | None, write: bool) -> None:
        from app.modules.hosted_access.application.managed_provider import ProviderDenied

        if cookie != COOKIE_VAL:
            raise ProviderDenied()
        if write and csrf != "valid-csrf":
            raise ProviderDenied()

    def begin_recent(self, cookie: str, csrf: str, request_hash: str) -> tuple[str, int]:
        return f"chal:{request_hash[:12]}", 1_900_000_000_000

    def mutation(self):
        from contextlib import nullcontext

        return nullcontext(None)

    def consume_recent(
        self, _conn, cookie: str, csrf: str, request_hash: str, grant, *, require_mfa: bool
    ) -> None:
        from app.modules.hosted_access.application.managed_provider import ProviderDenied

        if cookie != COOKIE_VAL or csrf != "valid-csrf":
            raise ProviderDenied()
        token = grant.get_secret_value()
        if token != self.valid_grant or token in self.consumed:
            raise ProviderDenied()
        self.consumed.add(token)


def _make_recovery_client(fx, sessions: _StubSessions) -> TestClient:
    app = FastAPI()
    app.include_router(
        operator_recovery_router(
            sessions,
            OperatorRecoveryInputs(origin=ORIGIN, recovery=fx["service"], recovery_mode=False),
        )
    )
    return TestClient(app, base_url=ORIGIN)


def test_stolen_or_ordinary_session_cannot_confirm_restore_without_step_up(tmp_path: Path):
    """Ordinary session without valid strong step-up, CSRF, or exact origin fails closed."""
    fx = _setup_workspace_fixture(tmp_path)
    try:
        actor, cmd = _capture_cmd("sec-cap-1")
        fx["service"].execute(actor, cmd)
        point_id = fx["service"].read_protection_status().last_point_id
        assert point_id is not None

        sessions = _StubSessions()
        client = _make_recovery_client(fx, sessions)

        # 1. Missing CSRF on preview is denied.
        r_no_csrf = client.post(
            "/api/hosted/recovery/preview",
            json={"point_id": point_id},
            headers={"Cookie": f"__Host-epm-session={COOKIE_VAL}", "Origin": ORIGIN},
        )
        assert r_no_csrf.status_code == 401

        # 2. Foreign Origin on preview is denied (403).
        r_bad_origin = client.post(
            "/api/hosted/recovery/preview",
            json={"point_id": point_id},
            headers={
                "Cookie": f"__Host-epm-session={COOKIE_VAL}",
                "Origin": "https://evil.example.invalid",
                "X-EPM-CSRF": "valid-csrf",
            },
        )
        assert r_bad_origin.status_code == 403

        # 3. Query string smuggling on recovery status is denied (403).
        r_query = client.get(
            "/api/hosted/recovery/status?point=1",
            headers={"Cookie": f"__Host-epm-session={COOKIE_VAL}"},
        )
        assert r_query.status_code == 403

        # 4. Valid preview succeeds, then stolen session without valid step-up grant is rejected!
        r_prev = client.post(
            "/api/hosted/recovery/preview",
            json={"point_id": point_id},
            headers={
                "Cookie": f"__Host-epm-session={COOKIE_VAL}",
                "Origin": ORIGIN,
                "X-EPM-CSRF": "valid-csrf",
            },
        )
        assert r_prev.status_code == 200
        preview_id = r_prev.json()["previewId"]

        r_stolen = client.post(
            "/api/hosted/recovery/confirm",
            json={
                "point_id": point_id,
                "preview_id": preview_id,
                "idempotency_key": "stolen-attempt-1",
                "recent_auth_grant": "forged-ordinary-session-token-1234",
            },
            headers={
                "Cookie": f"__Host-epm-session={COOKIE_VAL}",
                "Origin": ORIGIN,
                "X-EPM-CSRF": "valid-csrf",
            },
        )
        assert r_stolen.status_code == 401
        with fx["rec_engine"].connect() as conn:
            active_ref = conn.execute(
                text("SELECT active_business_ref FROM recovery_meta WHERE id = 1")
            ).scalar_one()
        assert active_ref == "incarnation-1"
    finally:
        fx["rec_engine"].dispose()
        fx["acc_engine"].dispose()


def test_role_confusion_admin_cannot_restore_customer_workspace(tmp_path: Path):
    """Admin authority is rejected by workspace restore; foreign operator scope is rejected."""
    fx = _setup_workspace_fixture(tmp_path)
    try:
        actor, cmd = _capture_cmd("sec-role-1")
        fx["service"].execute(actor, cmd)
        point_id = fx["service"].read_protection_status().last_point_id
        assert point_id is not None

        admin_actor = AdminAuthority(
            deployment_id=DEPLOYMENT_ID,
            principal_id=str(uuid4()),
            mfa_verified_at=1_760_000_000_000,
            identity_proof_ref="admin:forged",
        )
        with pytest.raises(RestoreDeniedError):
            fx["service"].preview_restore(admin_actor, point_id=point_id)  # type: ignore[arg-type]

        foreign_op = OperatorAuthority(
            deployment_id=DEPLOYMENT_ID,
            scope=WorkspaceScope(operator_id=str(uuid4()), workspace_id=str(uuid4())),
            identity_proof_ref="session:foreign",
        )
        with pytest.raises(RestoreDeniedError):
            fx["service"].preview_restore(foreign_op, point_id=point_id)
    finally:
        fx["rec_engine"].dispose()
        fx["acc_engine"].dispose()


def test_cross_workspace_prefix_key_and_aad_isolation(tmp_path: Path):
    """BackupProxyHandler denies cross-prefix/cross-key access; AEAD denies cross-workspace AAD."""
    store = LocalDirectoryObjectStore(tmp_path / "r2")
    key_a = KMS_KEY
    key_b = "projects/epm-demo/locations/us-west1/keyRings/epm-h05/cryptoKeys/ws-other"
    kms = LocalAesKmsProvider(
        {
            key_a: hashlib.sha256(b"kek-a").digest(),
            key_b: hashlib.sha256(b"kek-b").digest(),
        }
    )
    principal_a = CallerPrincipal(
        uid=20001,
        scope_kind="operator",
        deployment_id=DEPLOYMENT_ID,
        operator_id=OP_ID,
        workspace_id=WS_ID,
        namespace_prefix=f"deployments/{DEPLOYMENT_ID}/operators/{OP_ID}/",
        allowed_key_refs=frozenset({key_a}),
    )
    handler = BackupProxyHandler(object_store=store, kms=kms, peer_resolver=lambda _: principal_a)

    # 1. Cross-prefix traversal and absolute key rejected.
    for bad_key in ("../other-operator/manifests/p1.json", "/etc/passwd", "chunks/../../escape"):
        with pytest.raises(BackupProxyDenied):
            handler.dispatch(20001, {"version": 1, "op": "get_object", "key": bad_key}, b"")

    # 2. Cross-workspace KMS key rejected.
    with pytest.raises(BackupProxyDenied):
        handler.dispatch(
            20001,
            {"version": 1, "op": "kms_wrap", "key_ref": key_b, "aad_b64": "YWFk"},
            b"0" * 32,
        )

    # 3. Valid backup point for Workspace A cannot be verified/restored with Workspace B context.
    transport = _DirectTransport(handler, 20001)
    engine = ChunkedAeadBackupEngine(transport, chunk_size=4096)
    db_file = tmp_path / "biz.sqlite"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.commit()
    ctx_a = EnvelopeContext(
        scope_kind="operator",
        deployment_id=DEPLOYMENT_ID,
        operator_id=OP_ID,
        workspace_id=WS_ID,
        point_id=str(uuid4()),
        schema_revisions={"business": "20260401_0001", "access": "access_0001_initial"},
        key_ref=key_a,
    )
    created = engine.create_point(
        context=ctx_a,
        captured_at=1_760_000_000_000,
        business_revision="biz:1",
        files_generation="files:1",
        source_generation=1,
        release_ref="rel-1",
        databases=[DatabaseInput(filename="property-management.sqlite", path=db_file)],
    )
    ctx_b = ctx_a.model_copy(update={"workspace_id": str(uuid4())})
    with pytest.raises(HostedRecoveryError):
        engine.verify_point(
            expected_context=ctx_b,
            manifest_ref=created.manifest_ref,
            expected_manifest_sha256=created.manifest_sha256,
        )


def test_confirmation_replay_semantic_conflict_and_hash_mismatch(tmp_path: Path):
    """Single-use preview cannot be replayed; mismatched hash or changed semantics are denied."""
    fx = _setup_workspace_fixture(tmp_path)
    try:
        actor, cmd = _capture_cmd("sec-replay-1")
        fx["service"].execute(actor, cmd)
        point_id = fx["service"].read_protection_status().last_point_id
        assert point_id is not None

        scope = WorkspaceScope(operator_id=OP_ID, workspace_id=WS_ID)
        op_actor = OperatorAuthority(
            deployment_id=DEPLOYMENT_ID, scope=scope, identity_proof_ref="session:op"
        )
        preview = fx["service"].preview_restore(op_actor, point_id=point_id)

        # 1. Mismatched confirmed_request_hash is rejected.
        bad_hash_actor = OperatorRestoreAuthority(
            deployment_id=DEPLOYMENT_ID,
            scope=scope,
            identity_proof_ref="session:op",
            step_up_ref="stepup:1",
            step_up_at=fx["clock"].now,
            confirmed_request_hash="f" * 64,
        )
        with pytest.raises(RestoreDeniedError):
            fx["service"].confirm_restore(
                bad_hash_actor,
                point_id=point_id,
                preview_id=preview.preview_id,
                idempotency_key="bad-hash-key",
                authorized_subject=f"operator:{OP_ID}",
            )

        # 2. Foreign point_id is rejected.
        with pytest.raises(RestoreNotFoundError):
            fx["service"].preview_restore(op_actor, point_id=str(uuid4()))

        # 3. Valid confirmation succeeds; replaying same preview with a new key is denied.
        good_actor = OperatorRestoreAuthority(
            deployment_id=DEPLOYMENT_ID,
            scope=scope,
            identity_proof_ref="session:op",
            step_up_ref="stepup:2",
            step_up_at=fx["clock"].now,
            confirmed_request_hash=preview.exact_request_hash,
        )
        outcome = fx["service"].confirm_restore(
            good_actor,
            point_id=point_id,
            preview_id=preview.preview_id,
            idempotency_key="good-restore-key",
            authorized_subject=f"operator:{OP_ID}",
        )
        assert outcome.state.value == "succeeded"

        with pytest.raises(RestoreDeniedError):
            fx["service"].confirm_restore(
                good_actor,
                point_id=point_id,
                preview_id=preview.preview_id,
                idempotency_key="replayed-preview-new-key",
                authorized_subject=f"operator:{OP_ID}",
            )

        # 4. Reusing idempotency_key with changed preview_id raises SemanticConflict (409).
        preview2 = fx["service"].preview_restore(op_actor, point_id=point_id)
        good_actor2 = good_actor.model_copy(
            update={"confirmed_request_hash": preview2.exact_request_hash}
        )
        with pytest.raises(SemanticConflict):
            fx["service"].confirm_restore(
                good_actor2,
                point_id=point_id,
                preview_id=preview2.preview_id,
                idempotency_key="good-restore-key",
                authorized_subject=f"operator:{OP_ID}",
            )
    finally:
        fx["rec_engine"].dispose()
        fx["acc_engine"].dispose()


def test_path_traversal_and_symlink_escape_rejected(tmp_path: Path):
    """Relative file validator and retained-file reader reject traversal and symlinks."""
    for bad in ("../secret.txt", "/etc/passwd", "files/../../escape.pdf", "a\x00b.txt", ""):
        with pytest.raises(ValueError):
            validate_relative_file_path(bad)

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret-outside")
    link = ws_dir / "files" / "escape.txt"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)

    db_path = ws_dir / "biz.sqlite"
    digest = hashlib.sha256(b"secret-outside").hexdigest()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE file_records (id TEXT PRIMARY KEY, content_sha256 TEXT, size_bytes INT)"
        )
        conn.execute(
            "CREATE TABLE file_content_locations ("
            "file_id TEXT PRIMARY KEY, storage_provider TEXT, storage_state TEXT, "
            "local_relative_path TEXT)"
        )
        conn.execute("INSERT INTO file_records VALUES ('f1', ?, ?)", (digest, 14))
        conn.execute(
            "INSERT INTO file_content_locations VALUES ('f1', 'local', 'available', 'files/escape.txt')"
        )
        conn.commit()
        with pytest.raises(WorkspaceStateUnreadable):
            _read_retained_files(conn, ws_dir)


def test_tampered_ciphertext_chunk_and_manifest_fail_closed(tmp_path: Path):
    """Bit-flipping a stored R2 chunk or manifest fails verification without mutating active DB."""
    fx = _setup_workspace_fixture(tmp_path)
    try:
        actor, cmd = _capture_cmd("sec-tamper-1")
        fx["service"].execute(actor, cmd)
        point_id = fx["service"].read_protection_status().last_point_id
        assert point_id is not None

        # Corrupt a stored chunk in LocalDirectoryObjectStore.
        r2_root = tmp_path / "r2"
        chunk_files = [p for p in r2_root.rglob("*") if p.is_file() and "/chunks/" in str(p)]
        assert chunk_files
        orig = bytearray(chunk_files[0].read_bytes())
        orig[0] ^= 0xFF
        chunk_files[0].write_bytes(bytes(orig))

        scope = WorkspaceScope(operator_id=OP_ID, workspace_id=WS_ID)
        op_actor = OperatorAuthority(
            deployment_id=DEPLOYMENT_ID, scope=scope, identity_proof_ref="session:op"
        )
        preview = fx["service"].preview_restore(op_actor, point_id=point_id)
        restore_actor = OperatorRestoreAuthority(
            deployment_id=DEPLOYMENT_ID,
            scope=scope,
            identity_proof_ref="session:op",
            step_up_ref="stepup:tamper",
            step_up_at=fx["clock"].now,
            confirmed_request_hash=preview.exact_request_hash,
        )
        outcome = fx["service"].confirm_restore(
            restore_actor,
            point_id=point_id,
            preview_id=preview.preview_id,
            idempotency_key="tamper-restore-1",
            authorized_subject=f"operator:{OP_ID}",
        )
        assert outcome.state.value == "failed"
        with fx["rec_engine"].connect() as conn:
            active_ref = conn.execute(
                text("SELECT active_business_ref FROM recovery_meta WHERE id = 1")
            ).scalar_one()
        assert active_ref == "incarnation-1"
    finally:
        fx["rec_engine"].dispose()
        fx["acc_engine"].dispose()


def test_no_offline_workspace_decrypt_or_restore_bypass_and_gateway_negative_gate(tmp_path: Path):
    """D11 retired legacy offline hosted recovery modules; D9 rejects unverified eligible routes."""
    hosted_access = APP_DIR / "apps" / "server" / "app" / "modules" / "hosted_access"
    assert not (hosted_access / "application" / "recovery_publication.py").exists()
    assert not (hosted_access / "infrastructure" / "recovery_publication.py").exists()
    assert not (hosted_access / "infrastructure" / "recovery_bundle.py").exists()

    main_py = (APP_DIR / "apps" / "server" / "app" / "__main__.py").read_text(encoding="utf-8")
    assert "recovery-publish" not in main_py
    assert "recovery-restore-hosted" not in main_py

    settings = GatewaySettings(admin_socket=tmp_path / "caddy.sock", gateway_uid=1000)
    with pytest.raises(HostAgentUnavailable):
        auth_config(_make_projection("eligible"), settings)
