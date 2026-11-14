"""H03.1 pure-state matrix (synthetic snapshots, no provider/store authority).

Covers valid row/JSON shapes, required/strict fields, method/temporal failures,
cross-device pairing and renewal cap/fences/deadlines. Deterministic hashing covers
repeat inspection only. CAS/idempotent effects, rollback, SQL constraints, retention,
backup/restore and query budgets require owning adapters and are not exercised here.
"""

from uuid import UUID

import pytest
from pydantic import ValidationError

from app.modules.hosted_access.application.identity_setup import DAY, HOUR, MINUTE
from app.modules.hosted_access.application.identity_states import (
    AccessSessionState,
    AdminSessionState,
    EmailContinuationState,
    LIVE_SESSION_CAP,
    LoginAttemptState,
    LoginHandoffState,
    ManagedIdentitySessionState,
    RenewalAdmission,
    SourceLoginAttemptState,
    check_continuation_context,
    check_continuation_pairing,
    check_managed_login_policy,
    check_source_binding_emission,
)
from app.platform.hosted_contracts.semantic import SemanticRequest, semantic_hash

NOW = 100 * DAY
ORIGIN = "https://operator.example.test"
HASH = "a" * 64
OTHER_HASH = "b" * 64


def uid(number):
    return str(UUID(int=number))


def login_data(**changes):
    return (
        dict(
            attempt_id=uid(1),
            purpose="operator_login",
            operator_id=uid(2),
            parent_managed_session_id=None,
            source_attempt_id=uid(3),
            source_browser_hash=HASH,
            central_browser_hash=OTHER_HASH,
            method="email_link",
            email_key="realm:person@example.test",
            target_origin=ORIGIN,
            return_path="/properties",
            confirmed_request_hash=None,
            last_delivery_at=None,
            last_delivery_code=None,
            state="pending",
            created_at=NOW,
            expires_at=NOW + 15 * MINUTE,
            revision=1,
        )
        | changes
    )


def managed_data(**changes):
    return (
        dict(
            managed_session_id=uid(4),
            cookie_hash=HASH,
            purpose="operator",
            operator_id=uid(2),
            issuer="realm",
            subject="subject",
            email_key="realm:person@example.test",
            method="email_link",
            authenticated_at=NOW,
            mfa_verified_at=None,
            issued_at=NOW,
            provider_valid_until=NOW + 14 * DAY,
            remembered_until=NOW + 30 * DAY,
            revocation_checked_at=NOW,
            revocation_valid_until=NOW + 5 * MINUTE,
            revoked_at=None,
            revision=1,
        )
        | changes
    )


def continuation_data(**changes):
    return (
        dict(
            continuation_id=uid(5),
            original_attempt_id=uid(1),
            code_hash=HASH,
            central_browser_hash=OTHER_HASH,
            operator_id=uid(2),
            target_origin=ORIGIN,
            access_epoch=1,
            managed_session_id=None,
            replacement_attempt_id=None,
            source_attempt_id=None,
            source_binding_hash=None,
            handoff_id=None,
            state="verifying",
            created_at=NOW,
            expires_at=NOW + 5 * MINUTE,
            revision=1,
        )
        | changes
    )


def handoff_data(**changes):
    return (
        dict(
            handoff_id=uid(6),
            operator_id=uid(2),
            browser_state_hash=HASH,
            nonce_hash=HASH,
            code_hash=OTHER_HASH,
            target_origin=ORIGIN,
            issuer="realm",
            subject="subject",
            assignment_revision=1,
            access_epoch=1,
            state="issued",
            expires_at=NOW + 5 * MINUTE,
            redeemed_at=None,
            created_at=NOW,
            attempt_id=uid(1),
            managed_session_id=uid(4),
            identity_operation_id=uid(7),
            source_receipt_ref=None,
        )
        | changes
    )


def source_data(**changes):
    return (
        dict(
            attempt_id=uid(3),
            browser_challenge_hash=HASH,
            access_epoch=1,
            resource_generation=1,
            return_path="/properties",
            remembered=True,
            state="pending",
            handoff_id=None,
            continuation_id=None,
            binding_assertion_hash=None,
            binding_expires_at=None,
            created_at=NOW,
            expires_at=NOW + 15 * MINUTE,
            revision=1,
        )
        | changes
    )


def session_data(**changes):
    return (
        dict(
            session_hash=HASH,
            csrf_hash=OTHER_HASH,
            actor_subject="subject",
            handoff_id=uid(10),
            generation=1,
            access_epoch=1,
            issued_at=NOW - DAY,
            expires_at=NOW + HOUR,
            managed_valid_until=NOW + HOUR,
            last_seen_at=NOW,
            revoked_at=None,
            session_id=uid(8),
            managed_session_id=uid(9),
            managed_observation_revision=1,
            revocation_valid_until=NOW - DAY + MINUTE,
            remembered_until=NOW + 29 * DAY,
            display_label="Browser on laptop",
            renewed_from_session_id=None,
        )
        | changes
    )


def admin_data(**changes):
    return (
        dict(
            session_hash=HASH,
            principal_id=uid(11),
            csrf_hash=HASH,
            generation=1,
            authenticated_at=NOW,
            mfa_verified_at=NOW,
            expires_at=NOW + 8 * HOUR,
            last_seen_at=NOW,
            revoked_at=None,
            managed_session_id=uid(4),
            managed_valid_until=NOW + DAY,
            revocation_valid_until=NOW + MINUTE,
        )
        | changes
    )


def renewal_data(**changes):
    return (
        dict(
            prior=AccessSessionState(**session_data()),
            fresh_managed=ManagedIdentitySessionState(
                **managed_data(remembered_until=NOW + 29 * DAY)
            ),
            handoff=LoginHandoffState(**handoff_data(state="redeeming")),
            source_attempt=SourceLoginAttemptState(
                **source_data(state="redeeming", handoff_id=uid(6))
            ),
            login_attempt=LoginAttemptState(
                **login_data(purpose="renewal", parent_managed_session_id=uid(9), state="verified")
            ),
            now=NOW,
            current_operator_id=uid(2),
            current_subject="subject",
            current_issuer="realm",
            current_target_origin=ORIGIN,
            current_assignment_revision=1,
            current_access_epoch=1,
            current_session_generation=1,
            current_resource_generation=1,
            observed_prior_resource_generation=1,
            current_binding_id=uid(12),
            observed_prior_binding_id=uid(12),
            effective_access="enabled",
            maintenance_operation_id=None,
            not_before=NOW - HOUR,
            live_session_count=32,
        )
        | changes
    )


ROWS = [
    (LoginAttemptState, login_data),
    (EmailContinuationState, continuation_data),
    (ManagedIdentitySessionState, managed_data),
    (LoginHandoffState, handoff_data),
    (SourceLoginAttemptState, source_data),
    (AccessSessionState, session_data),
    (AdminSessionState, admin_data),
    (RenewalAdmission, renewal_data),
]


@pytest.mark.parametrize("model,factory", ROWS)
def test_versioned_strict_frozen_semantic_round_trip(model, factory):
    value = model(**factory())
    assert isinstance(value, SemanticRequest)
    restored = model.model_validate_json(value.model_dump_json())
    assert restored == value
    assert semantic_hash(restored) == semantic_hash(value)
    with pytest.raises(ValidationError):
        model(**(factory() | {"contract_version": "h03.identity.v2"}))
    with pytest.raises(ValidationError):
        model(**(factory() | {"raw_provider_token": "secret"}))
    with pytest.raises(ValidationError):
        value.contract_version = "h03.identity.v1"


@pytest.mark.parametrize("model,factory", ROWS)
def test_every_nondefault_column_is_required(model, factory):
    data = factory()
    for name, field in model.model_fields.items():
        if field.is_required():
            missing = {key: value for key, value in data.items() if key != name}
            with pytest.raises(ValidationError):
                model(**missing)


@pytest.mark.parametrize(
    "changes",
    [
        {"revision": True},
        {"revision": "1"},
        {"revision": 0},
        {"created_at": 1.5},
        {"created_at": -1},
        {"attempt_id": "not-a-uuid"},
        {"central_browser_hash": "A" * 64},
        {"expires_at": NOW},
        {"expires_at": NOW + 15 * MINUTE + 1},
        {"source_attempt_id": None},
        {"source_browser_hash": None},
        {"operator_id": None},
        {"method": "google_totp"},
        {"method": "password"},
        {"email_key": None},
        {"delivery_attempts": 1},
        {"last_delivery_code": "sent"},
        {"delivery_attempts": 1, "last_delivery_at": NOW - 1},
        {"delivery_attempts": 1, "last_delivery_at": NOW + 15 * MINUTE},
        {"purpose": "renewal"},
        {"purpose": "recent_auth"},
        {"confirmed_request_hash": HASH},
        {"state": "unknown"},
    ],
)
def test_login_negative_invariants(changes):
    with pytest.raises(ValidationError):
        LoginAttemptState(**login_data(**changes))


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.test",
        "//evil.test",
        "/auth/start",
        "/API/run",
        "/%61uth/start",
        "/properties?code=secret",
        "/properties#token",
        "/a/../auth/start",
        "/a/%2e%2e/x",
        "/a%5cb",
        "/a%0ab",
        "/a%252fb",
    ],
)
def test_return_paths_reject_capability_and_routing_ambiguities(path):
    with pytest.raises(ValidationError):
        LoginAttemptState(**login_data(return_path=path))


@pytest.mark.parametrize(
    "origin",
    [
        "http://operator.example.test",
        ORIGIN + "/",
        ORIGIN + ":443",
        "https://OPERATOR.example.test",
        "https://user@operator.example.test",
        ORIGIN + "?code=secret",
        "https://localhost",
    ],
)
def test_shared_exact_origin_contract(origin):
    with pytest.raises(ValidationError):
        LoginAttemptState(**login_data(target_origin=origin))


def test_admin_login_and_recent_auth_purpose_rules():
    admin = login_data(
        purpose="admin_login",
        operator_id=None,
        source_attempt_id=None,
        source_browser_hash=None,
        method="google_totp",
        email_key=None,
    )
    assert LoginAttemptState(**admin).purpose == "admin_login"
    for change in [{"operator_id": uid(2)}, {"method": "google"}, {"source_attempt_id": uid(3)}]:
        with pytest.raises(ValidationError):
            LoginAttemptState(**(admin | change))
    recent = admin | dict(
        purpose="recent_auth", parent_managed_session_id=uid(4), confirmed_request_hash=HASH
    )
    assert LoginAttemptState(**recent).confirmed_request_hash == HASH
    for change in [{"parent_managed_session_id": None}, {"confirmed_request_hash": None}]:
        with pytest.raises(ValidationError):
            LoginAttemptState(**(recent | change))


@pytest.mark.parametrize(
    "changes",
    [
        {"expires_at": NOW + 5 * MINUTE + 1},
        {"state": "verified"},
        {"state": "paired"},
        {"replacement_attempt_id": uid(13)},
        {"handoff_id": uid(6)},
        {
            "replacement_attempt_id": uid(1),
            "source_attempt_id": uid(14),
            "source_binding_hash": HASH,
            "managed_session_id": uid(4),
            "state": "paired",
        },
        {
            "state": "completed",
            "managed_session_id": uid(4),
            "replacement_attempt_id": uid(13),
            "source_attempt_id": uid(14),
            "source_binding_hash": HASH,
        },
    ],
)
def test_continuation_required_fields_and_fresh_pairing(changes):
    with pytest.raises(ValidationError):
        EmailContinuationState(**continuation_data(**changes))


def pairing_snapshots():
    continuation = EmailContinuationState(
        **continuation_data(
            state="paired",
            managed_session_id=uid(4),
            replacement_attempt_id=uid(13),
            source_attempt_id=uid(14),
            source_binding_hash=OTHER_HASH,
        )
    )
    replacement = LoginAttemptState(
        **login_data(attempt_id=uid(13), source_attempt_id=uid(14), source_browser_hash="d" * 64)
    )
    source = SourceLoginAttemptState(
        **source_data(
            attempt_id=uid(14),
            browser_challenge_hash="d" * 64,
            continuation_id=uid(5),
            binding_assertion_hash=OTHER_HASH,
            binding_expires_at=NOW + 5 * MINUTE,
        )
    )
    return continuation, replacement, source


def test_cross_device_completion_uses_new_binding_and_retains_original_context():
    continuation, replacement, source = pairing_snapshots()
    original = LoginAttemptState(**login_data(state="superseded"))
    managed = ManagedIdentitySessionState(**managed_data())
    check_continuation_context(continuation, original, managed)
    check_continuation_pairing(continuation, replacement, source, original)
    check_source_binding_emission(source, NOW)
    # The completing central browser may differ from the initiating one.
    original = LoginAttemptState(**login_data(central_browser_hash="c" * 64))
    check_continuation_context(continuation, original, managed)


@pytest.mark.parametrize(
    "changes",
    [
        {"central_browser_hash": "c" * 64},
        {"source_browser_hash": OTHER_HASH},
        {"source_attempt_id": uid(3)},
        {"target_origin": "https://other.example.test"},
        {"operator_id": uid(15)},
        {"method": "google"},
    ],
)
def test_cross_device_cannot_substitute_old_source_or_completing_browser(changes):
    continuation, replacement, source = pairing_snapshots()
    changed = LoginAttemptState.model_validate(replacement.model_dump() | changes)
    with pytest.raises(ValueError, match="pairing"):
        check_continuation_pairing(continuation, changed, source, LoginAttemptState(**login_data()))


@pytest.mark.parametrize(
    "changes",
    [
        {"method": "google"},
        {"email_key": "realm:other@example.test"},
        {"target_origin": "https://other.example.test"},
        {"expires_at": NOW + MINUTE},
    ],
)
def test_continuation_original_target_email_and_expiry_are_pinned(changes):
    continuation, _, _ = pairing_snapshots()
    with pytest.raises(ValueError):
        check_continuation_context(
            continuation,
            LoginAttemptState(**login_data(**changes)),
            ManagedIdentitySessionState(**managed_data()),
        )


def test_continuation_requires_proof_and_cannot_outlive_it():
    continuation, _, _ = pairing_snapshots()
    original = LoginAttemptState(**login_data())
    with pytest.raises(ValueError):
        check_continuation_context(continuation, original, None)
    proof = ManagedIdentitySessionState(
        **managed_data(provider_valid_until=NOW + MINUTE, revocation_valid_until=NOW + MINUTE)
    )
    with pytest.raises(ValueError):
        check_continuation_context(continuation, original, proof)


@pytest.mark.parametrize(
    "changes",
    [
        {"authenticated_at": NOW + 1},
        {"provider_valid_until": NOW},
        {"provider_valid_until": NOW + 14 * DAY + 1},
        {"remembered_until": NOW + 30 * DAY + 1},
        {"revocation_checked_at": NOW - 1},
        {"revocation_valid_until": NOW + 5 * MINUTE + 1},
        {"provider_valid_until": NOW + MINUTE},
        {"revoked_at": NOW - 1},
        {"purpose": "admin"},
        {"operator_id": None},
        {"method": "google_totp"},
        {"mfa_verified_at": NOW},
    ],
)
def test_managed_proof_negative_temporal_and_purpose_invariants(changes):
    with pytest.raises(ValidationError):
        ManagedIdentitySessionState(**managed_data(**changes))


def test_admin_requires_completed_mfa_and_source_session_eight_hour_ceiling():
    admin = managed_data(
        purpose="admin", operator_id=None, method="google_totp", mfa_verified_at=NOW
    )
    assert ManagedIdentitySessionState(**admin).purpose == "admin"
    for change in [{"mfa_verified_at": None}, {"mfa_verified_at": NOW + 1}, {"method": "google"}]:
        with pytest.raises(ValidationError):
            ManagedIdentitySessionState(**(admin | change))
    for change in [
        {"expires_at": NOW + 8 * HOUR + 1},
        {"mfa_verified_at": NOW - 1},
        {"managed_valid_until": NOW + HOUR},
        {"revocation_valid_until": NOW},
    ]:
        with pytest.raises(ValidationError):
            AdminSessionState(**admin_data(**change))


def test_unremembered_proof_is_at_most_eight_hours():
    managed = ManagedIdentitySessionState(**managed_data())
    with pytest.raises(ValueError):
        check_managed_login_policy(managed, False)
    short = ManagedIdentitySessionState(
        **managed_data(provider_valid_until=NOW + 8 * HOUR, remembered_until=NOW + 8 * HOUR)
    )
    check_managed_login_policy(short, False)
    check_managed_login_policy(managed, True)


@pytest.mark.parametrize(
    "changes",
    [
        {"code_hash": None},
        {"subject": None},
        {"issuer": None},
        {"expires_at": NOW + 5 * MINUTE + 1},
        {"state": "initiated"},
        {"state": "redeemed"},
        {"redeemed_at": NOW},
        {"source_receipt_ref": "receipt"},
        {"state": "redeemed", "redeemed_at": NOW + 5 * MINUTE, "source_receipt_ref": "receipt"},
    ],
)
def test_handoff_identity_redemption_and_receipt_invariants(changes):
    with pytest.raises(ValidationError):
        LoginHandoffState(**handoff_data(**changes))


def test_handoff_reserved_and_redeemed_states_have_distinct_safe_results():
    reserved = LoginHandoffState(**handoff_data(state="redeeming"))
    assert reserved.source_receipt_ref is None
    done = LoginHandoffState(
        **handoff_data(state="redeemed", redeemed_at=NOW, source_receipt_ref="receipt:source")
    )
    assert done.source_receipt_ref == "receipt:source"


@pytest.mark.parametrize(
    "changes",
    [
        {"remembered": 1},
        {"state": "completed"},
        {"state": "redeeming"},
        {"binding_assertion_hash": HASH},
        {"binding_expires_at": NOW + MINUTE},
        {"binding_assertion_hash": HASH, "binding_expires_at": NOW + MINUTE},
        {
            "continuation_id": uid(5),
            "binding_assertion_hash": HASH,
            "binding_expires_at": NOW + 16 * MINUTE,
        },
    ],
)
def test_source_attempt_required_binding_and_lifetime(changes):
    with pytest.raises(ValidationError):
        SourceLoginAttemptState(**source_data(**changes))


def test_source_assertion_emission_deadline_is_contextual():
    source = SourceLoginAttemptState(
        **source_data(
            continuation_id=uid(5), binding_assertion_hash=HASH, binding_expires_at=NOW + 6 * MINUTE
        )
    )
    with pytest.raises(ValueError):
        check_source_binding_emission(source, NOW)
    check_source_binding_emission(source, NOW + MINUTE)


@pytest.mark.parametrize(
    "changes",
    [
        {"expires_at": NOW - DAY},
        {"expires_at": NOW + 2 * HOUR},
        {"remembered_until": NOW},
        {"remembered_until": NOW + 30 * DAY},
        {"revocation_valid_until": NOW + 2 * HOUR},
        {"renewed_from_session_id": uid(8)},
        {"display_label": "<script>"},
        {"display_label": "Browser\nsecret"},
        {"revoked_at": NOW - 2 * DAY},
    ],
)
def test_access_session_proof_lineage_and_safe_metadata(changes):
    with pytest.raises(ValidationError):
        AccessSessionState(**session_data(**changes))


def test_live_renewal_at_cap_frees_own_slot_even_with_stale_prior_status():
    admission = RenewalAdmission(**renewal_data())
    assert admission.prior.revocation_valid_until < NOW
    assert admission.live_session_count == LIVE_SESSION_CAP
    assert admission.replacement_expires_at() == NOW + 14 * DAY


def test_expiry_only_renewal_requires_free_slot():
    prior = AccessSessionState(**session_data(expires_at=NOW))
    assert RenewalAdmission(**renewal_data(prior=prior, live_session_count=31))
    with pytest.raises(ValidationError, match="session_limit_reached"):
        RenewalAdmission(**renewal_data(prior=prior, live_session_count=32))


@pytest.mark.parametrize(
    "changes",
    [
        {"effective_access": "disabled"},
        {"maintenance_operation_id": uid(16)},
        {"current_access_epoch": 2},
        {"current_session_generation": 2},
        {"current_resource_generation": 2},
        {"current_binding_id": uid(17)},
        {"current_assignment_revision": 2},
        {"current_target_origin": "https://other.example.test"},
        {"current_subject": "other"},
        {"current_issuer": "other-realm"},
        {"current_operator_id": uid(17)},
        {"not_before": NOW + 1},
        {"live_session_count": 33},
        {"live_session_count": 0},
        {"now": NOW + 5 * MINUTE},
        {"now": NOW - 1},
    ],
)
def test_renewal_current_fences_status_and_cap(changes):
    with pytest.raises(ValidationError):
        RenewalAdmission(**renewal_data(**changes))


@pytest.mark.parametrize(
    "field,changes",
    [
        ("prior", {"revoked_at": NOW}),
        ("fresh_managed", {"revoked_at": NOW}),
        ("fresh_managed", {"remembered_until": NOW + 30 * DAY}),
        ("fresh_managed", {"managed_session_id": uid(9)}),
        ("handoff", {"state": "issued"}),
        ("handoff", {"managed_session_id": uid(18)}),
        ("source_attempt", {"browser_challenge_hash": OTHER_HASH}),
        ("source_attempt", {"remembered": False}),
        ("login_attempt", {"parent_managed_session_id": uid(18)}),
        ("login_attempt", {"created_at": NOW - MINUTE, "expires_at": NOW}),
    ],
)
def test_renewal_cannot_revive_logout_retarget_lineage_or_skip_handoff(field, changes):
    data = renewal_data()
    value = data[field]
    data[field] = type(value).model_validate(value.model_dump() | changes)
    with pytest.raises(ValidationError):
        RenewalAdmission(**data)


def test_renewal_provider_proof_can_outlive_original_lineage_but_cannot_extend_it():
    deadline = NOW + HOUR
    prior = AccessSessionState(**session_data(remembered_until=deadline))
    managed = ManagedIdentitySessionState(**managed_data(remembered_until=deadline))
    admission = RenewalAdmission(**renewal_data(prior=prior, fresh_managed=managed))
    assert managed.provider_valid_until > deadline
    assert admission.replacement_expires_at() == deadline
    with pytest.raises(ValidationError):
        RenewalAdmission(**renewal_data(prior=prior, fresh_managed=managed, now=deadline))


@pytest.mark.parametrize("reuse", ["attempt", "challenge"])
def test_continuation_cannot_reuse_original_destination_binding(reuse):
    continuation, replacement, source = pairing_snapshots()
    original = LoginAttemptState(**login_data())
    if reuse == "attempt":
        source = SourceLoginAttemptState.model_validate(
            source.model_dump() | {"attempt_id": uid(3)}
        )
        replacement = LoginAttemptState.model_validate(
            replacement.model_dump() | {"source_attempt_id": uid(3)}
        )
        continuation = EmailContinuationState.model_validate(
            continuation.model_dump() | {"source_attempt_id": uid(3)}
        )
    else:
        source = SourceLoginAttemptState.model_validate(
            source.model_dump() | {"browser_challenge_hash": HASH}
        )
        replacement = LoginAttemptState.model_validate(
            replacement.model_dump() | {"source_browser_hash": HASH}
        )
    with pytest.raises(ValueError, match="fresh signed destination"):
        check_continuation_pairing(continuation, replacement, source, original)


@pytest.mark.parametrize("deadline", ["proof", "status", "lineage"])
def test_renewal_deadlines_are_exclusive_even_at_exact_boundary(deadline):
    data = renewal_data()
    managed = managed_data(
        issued_at=NOW - 1,
        authenticated_at=NOW - 1,
        revocation_checked_at=NOW - 1,
        provider_valid_until=NOW + 14 * DAY - 1,
        revocation_valid_until=NOW + 5 * MINUTE - 1,
        remembered_until=NOW + 29 * DAY,
    )
    if deadline == "proof":
        managed.update(provider_valid_until=NOW, revocation_valid_until=NOW)
    elif deadline == "status":
        managed.update(revocation_valid_until=NOW)
    else:
        managed.update(remembered_until=NOW)
        data["prior"] = AccessSessionState(**session_data(expires_at=NOW, remembered_until=NOW))
    data["fresh_managed"] = ManagedIdentitySessionState(**managed)
    data["login_attempt"] = LoginAttemptState.model_validate(
        data["login_attempt"].model_dump() | {"created_at": NOW - 1, "expires_at": NOW + MINUTE}
    )
    with pytest.raises(ValidationError):
        RenewalAdmission(**data)


def test_persistence_subject_bound_remains_distinct_from_provider_uid_policy():
    assert ManagedIdentitySessionState(**managed_data(subject="s" * 1024))
    with pytest.raises(ValidationError):
        ManagedIdentitySessionState(**managed_data(subject="s" * 1025))


@pytest.mark.parametrize(
    "state", ["pending", "verified", "completed", "failed", "superseded", "expired"]
)
def test_terminal_attempts_retain_original_deadlines_and_bindings(state):
    attempt = LoginAttemptState(**login_data(state=state))
    assert attempt.source_browser_hash == HASH
    assert attempt.expires_at == NOW + 15 * MINUTE
