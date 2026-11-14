"""Durable central flow invariants with real SQLite and synthetic provider/source owners."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from pydantic import SecretStr
import pytest
from sqlalchemy import text

from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.tests.test_firebase_provider import NOW
from app.platform.hosted_schema import validate_schema
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import immediate_transaction
from app.platform.tests.test_hosted_schema import FIRST

pytest_plugins = ("app.modules.hosted_access.tests.central_fixtures",)

APPLICATION = Path(__file__).resolve().parents[6]


def test_google_completion_atomic_and_browser_bound(central, central_start):
    service, tick, _ = central
    attempt, browser = central_start(service, tick)
    with pytest.raises(ProviderDenied):
        service.complete_google(attempt, "x" * 43, SecretStr("proof"))
    result = service.complete_google(attempt, browser, SecretStr("proof"))
    assert result.result["state"] == "workspace_not_ready"
    assert result.cookie.get_secret_value() not in repr(result)
    with pytest.raises(ProviderDenied):
        service.complete_google(attempt, browser, SecretStr("proof"))
    assert service.provider.complete_google.call_count == 1
    with service.engine.connect() as connection:
        validate_schema(connection, HostedStore.ADMIN, application_directory=APPLICATION)
        assert connection.scalar(text("SELECT count(*) FROM main.managed_identity_sessions")) == 1


def test_email_reservation_survives_timeout_and_other_browser_cannot_redeem(central, central_start):
    service, tick, _ = central
    attempt, _ = central_start(service, tick, "email_link")
    service.provider.complete_email_link.side_effect = ProviderUnavailable()
    with pytest.raises(ProviderUnavailable):
        service.complete_email(
            attempt, "x" * 43, "A.B+tag@example.invalid", SecretStr("action-code")
        )
    result = service.complete_email(
        attempt, "x" * 43, "A.B+tag@example.invalid", SecretStr("action-code")
    )
    assert result["state"] == "unknown"
    with pytest.raises(ProviderDenied):
        service.complete_email(
            attempt, "y" * 43, "A.B+tag@example.invalid", SecretStr("action-code")
        )
    assert service.provider.complete_email_link.call_count == 1


def test_email_success_supersedes_original_without_replaying_cookie(central, central_start):
    service, tick, _ = central
    attempt, original_browser = central_start(service, tick, "email_link")
    completed = service.complete_email(
        attempt, "x" * 43, "A.B+tag@example.invalid", SecretStr("code")
    )
    resumed = service.complete_email(
        attempt, "x" * 43, "A.B+tag@example.invalid", SecretStr("code")
    )
    assert resumed["state"] == "verified"
    assert "cookie" not in resumed
    assert completed.result["continuationId"] == resumed["continuationId"]
    with service.engine.connect() as connection:
        validate_schema(connection, HostedStore.ADMIN, application_directory=APPLICATION)
        assert (
            connection.scalar(
                text("SELECT state FROM main.login_attempts WHERE attempt_id=:id"), {"id": attempt}
            )
            == "superseded"
        )


def test_concurrent_email_code_has_one_provider_call(central, central_start):
    service, tick, _ = central
    attempt, _ = central_start(service, tick, "email_link")

    def complete(_):
        return service.complete_email(
            attempt, "x" * 43, "A.B+tag@example.invalid", SecretStr("code")
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        list(workers.map(complete, range(2)))
    assert service.provider.complete_email_link.call_count == 1


def test_send_unknown_reserves_delivery_and_cooldown(central, central_start):
    service, tick, _ = central
    attempt, browser = central_start(service, tick, "email_link")
    service.provider.send_email_link.side_effect = ProviderUnavailable()
    with pytest.raises(ProviderUnavailable):
        service.send_email(attempt, browser, network="192.0.2.1")
    with pytest.raises(ProviderDenied):
        service.send_email(attempt, browser, network="192.0.2.1")
    assert service.provider.send_email_link.call_count == 1
    with service.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT last_delivery_code FROM main.login_attempts"))
            == "unknown"
        )


def invitations(service):
    from app.modules.hosted_access.infrastructure.central_invitations import CentralInvitations
    from app.modules.hosted_access.application.admin_admission import AdminPrincipal
    from app.modules.hosted_access.application.identity_states import AdminSessionState
    from app.modules.hosted_access.tests.test_identity_states import admin_data

    admin = Mock()
    admin.authenticate.return_value = AdminSessionState(
        **admin_data(
            authenticated_at=NOW * 1000,
            mfa_verified_at=NOW * 1000,
            expires_at=(NOW + 3600) * 1000,
            last_seen_at=NOW * 1000,
            managed_valid_until=(NOW + 3600) * 1000,
            revocation_valid_until=(NOW + 300) * 1000,
        )
    )
    admin._load.return_value = admin.authenticate.return_value
    admin._principal.return_value = AdminPrincipal(
        admin.authenticate.return_value.principal_id, True, 1
    )
    return CentralInvitations(service.engine, admin, clock=service.clock)


def test_unavailable_readiness_retains_invite_then_claim_has_original_receipt(
    central, central_start
):
    service, tick, _ = central
    attempt, browser = central_start(service, tick)
    completed = service.complete_google(attempt, browser, SecretStr("google-proof"))
    owner = invitations(service)
    invite, token = owner.issue(
        "admin-cookie", FIRST, expected_revision=1, access_epoch=1, expires_at=tick[0] + 600000
    )
    args = (attempt, completed.result["managedSessionId"], invite, token)
    assert owner.claim(*args, central_cookie=completed.cookie)["state"] == "workspace_not_ready"
    with service.engine.connect() as connection:
        assert connection.scalar(text("SELECT state FROM main.invitations")) == "pending_delivery"
    owner.readiness = Mock()
    owner.readiness.ready.return_value = True
    from app.modules.hosted_access.application.central_login import ClaimSourceReceipt

    owner.source_claim = Mock()
    owner.source_claim.claim.side_effect = lambda **values: ClaimSourceReceipt(
        **{key: values[key] for key in ("operation_id", "operator_id", "access_epoch")},
        receipt_ref="source-claim-original",
    )
    result = owner.claim(*args, central_cookie=completed.cookie)
    assert result["kind"] == "claim" and result["source_receipt_ref"] == "source-claim-original"
    owner.readiness.ready.side_effect = ProviderUnavailable()
    assert owner.claim(*args, central_cookie=completed.cookie) == result
    with service.engine.connect() as connection:
        validate_schema(connection, HostedStore.ADMIN, application_directory=APPLICATION)
        assert connection.scalar(text("SELECT count(*) FROM main.identity_commands")) == 1
        assert connection.scalar(text("SELECT subject FROM main.operators")) == "uid"


def test_reissue_revokes_prior_and_claim_requires_exact_cookie_and_email(central, central_start):
    service, tick, _ = central
    attempt, browser = central_start(service, tick)
    completed = service.complete_google(attempt, browser, SecretStr("proof"))
    owner = invitations(service)
    first, _ = owner.issue(
        "admin-cookie", FIRST, expected_revision=1, access_epoch=1, expires_at=tick[0] + 600000
    )
    second, token = owner.issue(
        "admin-cookie", FIRST, expected_revision=2, access_epoch=1, expires_at=tick[0] + 600000
    )
    with service.engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT state FROM main.invitations WHERE invitation_id=:id"), {"id": first}
            )
            == "revoked"
        )
    with pytest.raises(ProviderDenied):
        owner.claim(
            attempt,
            completed.result["managedSessionId"],
            second,
            token,
            central_cookie=SecretStr("different-browser"),
        )
    owner.readiness = Mock()
    owner.readiness.ready.return_value = True
    with immediate_transaction(service.engine) as connection:
        connection.execute(
            text(
                "UPDATE main.invitations SET email_key='other@example.invalid' WHERE invitation_id=:id"
            ),
            {"id": second},
        )
    with pytest.raises(ProviderDenied):
        owner.claim(
            attempt,
            completed.result["managedSessionId"],
            second,
            token,
            central_cookie=completed.cookie,
        )


def test_source_epoch_change_during_provider_call_rolls_back_managed_result(central, central_start):
    service, tick, _ = central
    attempt, browser = central_start(service, tick)
    result = service.provider.complete_google.return_value

    def exchange(*args, **kwargs):
        with immediate_transaction(service.engine) as connection:
            connection.execute(text("UPDATE main.operators SET access_epoch=access_epoch+1"))
        return result

    service.provider.complete_google.side_effect = exchange
    with pytest.raises(ProviderDenied):
        service.complete_google(attempt, browser, SecretStr("proof"))
    with service.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM main.managed_identity_sessions")) == 0


def test_email_unknown_retained_after_backup_restore(central, central_start, tmp_path):
    import sqlite3

    service, tick, path = central
    attempt, _ = central_start(service, tick, "email_link")
    service.provider.complete_email_link.side_effect = ProviderUnavailable()
    with pytest.raises(ProviderUnavailable):
        service.complete_email(
            attempt, "x" * 43, "A.B+tag@example.invalid", SecretStr("retained-code")
        )
    backup = tmp_path / "backup.sqlite"
    with sqlite3.connect(path) as source, sqlite3.connect(backup) as destination:
        source.backup(destination)
    from app.platform.sqlite_engine import create_sqlite_engine
    from app.modules.hosted_access.infrastructure.central_attempts import CentralAttempts
    from app.modules.hosted_access.infrastructure.central_login import CentralLogin

    restored_engine = create_sqlite_engine(backup)
    try:
        restored = CentralLogin(
            CentralAttempts(
                restored_engine,
                service.attempts.setup,
                service.attempts.source,
                clock=service.clock,
            ),
            service.provider,
            deployment_id=service.deployment_id,
        )
        assert (
            restored.complete_email(
                attempt, "x" * 43, "A.B+tag@example.invalid", SecretStr("retained-code")
            )["state"]
            == "unknown"
        )
        assert service.provider.complete_email_link.call_count == 1
        with restored_engine.connect() as connection:
            validate_schema(connection, HostedStore.ADMIN, application_directory=APPLICATION)
    finally:
        restored_engine.dispose()


def test_unknown_source_claim_reconciles_without_repeating_effect(central, central_start):
    from app.modules.hosted_access.application.central_login import ClaimSourceReceipt

    service, tick, _ = central
    attempt, browser = central_start(service, tick)
    completed = service.complete_google(attempt, browser, SecretStr("proof"))
    owner = invitations(service)
    invite, token = owner.issue(
        "admin-cookie", FIRST, expected_revision=1, access_epoch=1, expires_at=tick[0] + 600000
    )
    owner.readiness = Mock()
    owner.readiness.ready.return_value = True
    owner.source_claim = Mock()
    owner.source_claim.claim.side_effect = ProviderUnavailable()
    args = (attempt, completed.result["managedSessionId"], invite, token)
    assert owner.claim(*args, central_cookie=completed.cookie)["state"] == "claim_needs_checking"
    command = owner.source_claim.claim.call_args.kwargs
    owner.source_claim.original.return_value = ClaimSourceReceipt(
        **{key: command[key] for key in ("operation_id", "operator_id", "access_epoch")},
        receipt_ref="original-source-receipt",
    )
    result = owner.claim(*args, central_cookie=completed.cookie)
    assert result["source_receipt_ref"] == "original-source-receipt"
    assert owner.source_claim.claim.call_count == 1
    owner.source_claim.original.assert_called_once_with(command["operation_id"])
    with service.engine.connect() as connection:
        validate_schema(connection, HostedStore.ADMIN, application_directory=APPLICATION)


def test_invitation_reissue_stale_revision_cannot_revoke_new_invitation(central, central_start):
    service, tick, _ = central
    tick[0] = NOW * 1000
    owner = invitations(service)
    invite, _ = owner.issue(
        "admin-cookie", FIRST, expected_revision=1, access_epoch=1, expires_at=tick[0] + 600000
    )
    with pytest.raises(ProviderDenied):
        owner.issue(
            "admin-cookie", FIRST, expected_revision=1, access_epoch=1, expires_at=tick[0] + 600000
        )
    with service.engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT invitation_id FROM main.invitations WHERE state='pending_delivery'")
            )
            == invite
        )


def test_wrong_email_never_sends_and_expired_continuation_cannot_resume(central, central_start):
    service, tick, _ = central
    with pytest.raises(ProviderDenied):
        service.attempts.start("public-flow", method="email_link", email="wrong@example.invalid")
    attempt, _ = central_start(service, tick, "email_link")
    service.complete_email(attempt, "x" * 43, "A.B+tag@example.invalid", SecretStr("code"))
    tick[0] += 300000
    with pytest.raises(ProviderDenied):
        service.complete_email(attempt, "x" * 43, "A.B+tag@example.invalid", SecretStr("code"))
    assert service.provider.complete_email_link.call_count == 1


def test_verified_source_invitation_is_claimed_from_completion(central, central_start):
    from app.modules.hosted_access.application.central_login import ClaimSourceReceipt
    from app.modules.hosted_access.infrastructure.central_attempts import digest

    service, tick, _ = central
    tick[0] = NOW * 1000
    owner = invitations(service)
    invite, token = owner.issue(
        "admin-cookie", FIRST, expected_revision=1, access_epoch=1, expires_at=tick[0] + 600000
    )
    owner.readiness = Mock()
    owner.readiness.ready.return_value = True
    owner.source_claim = Mock()
    owner.source_claim.claim.side_effect = lambda **values: ClaimSourceReceipt(
        **{key: values[key] for key in ("operation_id", "operator_id", "access_epoch")},
        receipt_ref="verified-source-claim",
    )
    context = service.attempts.source.resolve_start.return_value.model_copy(
        update={
            "assignment_revision": 2,
            "invitation_id": invite,
            "invitation_hash": digest(token.get_secret_value()),
        }
    )
    service.attempts.source.resolve_start.return_value = context
    service.attempts.source.inspect_start.return_value = context
    service.invitations = owner
    attempt, browser = central_start(service, tick)
    result = service.complete_google(attempt, browser, SecretStr("proof"))
    assert result.result["claim"]["source_receipt_ref"] == "verified-source-claim"
    assert result.result["state"] == "workspace_not_ready"
    owner.source_claim.claim.assert_called_once()


def test_revoked_central_cookie_cannot_inspect_claim_receipts(central, central_start):
    service, tick, _ = central
    attempt, browser = central_start(service, tick)
    completed = service.complete_google(attempt, browser, SecretStr("proof"))
    owner = invitations(service)
    invite, token = owner.issue(
        "admin-cookie", FIRST, expected_revision=1, access_epoch=1, expires_at=tick[0] + 600000
    )
    owner.readiness = Mock()
    owner.readiness.ready.return_value = True
    assert (
        owner.claim(
            attempt,
            completed.result["managedSessionId"],
            invite,
            token,
            central_cookie=completed.cookie,
        )["state"]
        == "claim_needs_checking"
    )
    with immediate_transaction(service.engine) as connection:
        connection.execute(
            text("UPDATE main.managed_identity_sessions SET revoked_at=:now, revision=revision+1"),
            {"now": tick[0]},
        )
    with pytest.raises(ProviderDenied):
        owner.claim(
            attempt,
            completed.result["managedSessionId"],
            invite,
            token,
            central_cookie=completed.cookie,
        )


def test_attempt_capacity_rejects_before_adding_a_row(central, central_start):
    service, tick, _ = central
    for _ in range(32):
        central_start(service, tick)
    with pytest.raises(ProviderDenied):
        central_start(service, tick)
    with service.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM main.login_attempts")) == 32
