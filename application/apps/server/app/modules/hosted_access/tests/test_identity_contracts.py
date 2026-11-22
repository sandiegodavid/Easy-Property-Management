"""H03.1 deterministic negative fixtures, not provider/browser/native qualification."""

from pathlib import Path

from pydantic import ValidationError
import pytest

from app.modules.hosted_access.application.identity_setup import (
    IdentityOrigins,
    IdentityPolicy,
    IdentityRealm,
    IdentitySetup,
    require_verified_setup,
    require_immutable_realm,
)
from app.modules.hosted_access.application.identity_evidence import (
    HandoffEvidence,
    IdentityBinding,
    ManagedObservation,
    PrivateGrant,
    SessionReceipt,
    SourceBindingAssertion,
    require_current_grant,
)
from app.modules.hosted_access.application.identity_ports import VerifiedEmailLink
from app.modules.hosted_access.application.source_contracts import (
    SourceCommand,
    IssueSession,
    require_invocation,
)
from app.modules.host_agent.application.auth_routes import (
    ApplyAuthRoutes,
    IdentityCookiePolicy,
    AuthRouteManifest,
    AuthRouteObservation,
    SharedIdentityManifest,
)
from app.modules.host_agent.application.effect_contracts import EffectIdentity
from app.platform.hosted_contracts.authority import ServiceAuthority
from app.platform.hosted_contracts.operations import (
    CommandIntent,
    OperationReference,
    SemanticConflict,
    original_result,
    OperationOutcome,
    OperationState,
)
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import WorkspaceScope

ID = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
HASH = "a" * 64
SCOPE = WorkspaceScope(operator_id=ID, workspace_id=ID)


def setup():
    return IdentitySetup.model_validate_json(
        (
            Path(__file__).resolve().parents[6] / "deploy/hosted-mvp/identity/selection.json"
        ).read_bytes()
    )


def binding(**changes):
    return IdentityBinding(
        **(
            dict(
                deployment_id=ID,
                scope=SCOPE,
                binding_id=ID,
                resource_generation=1,
                access_epoch=1,
                assignment_revision=1,
                registered_origin_id=ID,
                target_origin="https://operator.epmdemo.xyz",
                issuer="identity-epmdemo-v1",
                subject="verified-uid",
            )
            | changes
        )
    )


def managed(**changes):
    return ManagedObservation(
        **(
            dict(
                managed_session_id=ID,
                revision=1,
                issuer="identity-epmdemo-v1",
                subject="verified-uid",
                method="google",
                purpose="operator",
                operator_id=ID,
                email_verified=True,
                authenticated_at=100,
                mfa_verified_at=None,
                issued_at=100,
                provider_valid_until=900000,
                remembered_until=900000,
                checked_at=100,
                valid_until=300100,
                revoked=False,
            )
            | changes
        )
    )


def handoff(**changes):
    return HandoffEvidence(
        **(
            dict(
                key_id="central-key-v1",
                binding=binding(),
                operation_id=ID,
                request_hash=HASH,
                nonce_hash=HASH,
                issued_at=100,
                expires_at=300100,
                handoff_id=ID,
                attempt_id=ID,
                source_attempt_id=ID,
                source_browser_hash=HASH,
                managed=managed(),
            )
            | changes
        )
    )


def test_selected_inputs_pin_confirmed_realm_callbacks_and_no_provider_acceptance():
    value = setup()
    assert value.realm.project_id == "project-47b72bb7-ba90-42c9-910"
    assert value.realm.tenant_id is None
    assert value.origins.central == "https://login.epmdemo.xyz"
    assert (value.deployment_sends_per_day, value.provider_sends_per_day) == (9, 10)
    assert value.configuration_state == "verified"
    assert value.provider_config_sha256 is not None
    require_verified_setup(value)
    unverified = IdentitySetup(
        **(
            value.model_dump()
            | {"configuration_state": "selected_not_verified", "provider_config_sha256": None}
        )
    )
    with pytest.raises(ValueError, match="not been independently verified"):
        require_verified_setup(unverified)
    with pytest.raises(ValidationError):
        IdentitySetup(
            **(
                value.model_dump()
                | {"configuration_state": "verified", "provider_config_sha256": None}
            )
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"issuer": "https://securetoken.google.com/foreign"},
        {"audience": "foreign"},
        {"alias": "https://securetoken.google.com/project"},
        {"operator_methods": ("google", "password")},
        {"admin_method": "google"},
        {"email_completion": "browser_password_token"},
        {"provider_token": "secret"},
    ],
)
def test_provider_input_denials(changes):
    with pytest.raises(ValidationError):
        IdentityRealm(**(setup().realm.model_dump() | changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"central": "https://login.epmdemo.xyz/"},
        {"admin": "https://login.epmdemo.xyz"},
        {"central": "http://login.epmdemo.xyz"},
        {"central": "https://*.epmdemo.xyz"},
        {"central": "https://LOGIN.epmdemo.xyz"},
        {"central": "https://login.epmdemo.xyz:443"},
        {"google_callback": "https://evil.invalid/__/auth/handler"},
        {"email_callback": "https://login.epmdemo.xyz/auth/complete?token=secret"},
    ],
)
def test_exact_origin_and_callback_denials(changes):
    with pytest.raises(ValidationError):
        IdentityOrigins(**(setup().origins.model_dump() | changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"remembered_ms": 2592000001},
        {"provider_status_ms": 300001},
        {"max_live_sessions": 33},
        {"browser_provider_persistence": "local"},
        {"refresh_credential_storage": "encrypted_vault"},
        {"attempt_ms": True},
        {"version": 2},
    ],
)
def test_accepted_policy_cannot_silently_drift(changes):
    with pytest.raises(ValidationError):
        IdentityPolicy(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"deployment_sends_per_day": 10},
        {"rate_key_rotation_ms": 1},
        {"rate_retention_ms": 86400000},
        {"source_signing_key_registry_ref": "identity-central-ed25519-v1"},
        {"signing_algorithm": "none"},
        {"provider_config_sha256": "not-a-digest"},
    ],
)
def test_setup_bounds_and_key_custody(changes):
    with pytest.raises(ValidationError):
        IdentitySetup(**(setup().model_dump() | changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"email_verified": False},
        {"purpose": "admin"},
        {"operator_id": None},
        {"valid_until": 300101},
        {"authenticated_at": 101},
        {"mfa_verified_at": 101},
        {"provider_valid_until": 100},
        {"remembered_until": 100},
    ],
)
def test_managed_proof_invariants(changes):
    with pytest.raises(ValidationError):
        managed(**changes)


def test_admin_requires_actual_completed_mfa_and_email_link_has_recognized_provenance():
    admin = managed(purpose="admin", operator_id=None, method="google_totp", mfa_verified_at=100)
    assert admin.purpose == "admin"
    with pytest.raises(ValidationError):
        VerifiedEmailLink(managed=managed(), reserved_code_hash=HASH)
    assert (
        VerifiedEmailLink(managed=managed(method="email_link"), reserved_code_hash=HASH).method
        == "email_link"
    )
    # Fresh provider proof may outlive a non-sliding remembered deadline.
    assert managed(remembered_until=500000).remembered_until < managed().provider_valid_until


@pytest.mark.parametrize(
    "changes",
    [
        {"binding": binding(subject="other-uid")},
        {"binding": binding(scope=WorkspaceScope(operator_id=OTHER, workspace_id=ID))},
        {"managed": managed(revoked=True)},
        {"expires_at": 300101},
        {"managed": managed(valid_until=300000)},
        {"session_token": "secret"},
    ],
)
def test_handoff_cannot_change_identity_or_outlive_verified_proof(changes):
    with pytest.raises(ValidationError):
        handoff(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"issuer_service": "owning_source"},
        {"audience": "epm:central-identity:v1"},
        {"expires_at": 300101},
        {"issued_at": 300100},
        {"purpose": "shell"},
    ],
)
def test_private_grant_purpose_signer_and_expiry(changes):
    with pytest.raises(ValidationError):
        PrivateGrant(
            **(
                handoff().model_dump(
                    exclude={
                        "managed",
                        "handoff_id",
                        "attempt_id",
                        "source_attempt_id",
                        "source_browser_hash",
                    }
                )
                | changes
            )
        )


def test_pairing_and_current_scope_checks_are_explicit_not_browser_authority():
    base = handoff().model_dump(
        exclude={
            "managed",
            "handoff_id",
            "attempt_id",
            "source_attempt_id",
            "source_browser_hash",
            "purpose",
            "issuer_service",
            "audience",
        }
    )
    assertion = SourceBindingAssertion(
        **base, continuation_id=ID, source_attempt_id=ID, source_browser_hash=HASH
    )
    assert assertion.audience == "epm:central-identity:v1"
    require_current_grant(
        handoff(), binding(), now=100, request_hash=HASH, audience="epm:owning-source:v1"
    )
    for current in (
        binding(access_epoch=2),
        binding(resource_generation=2),
        binding(assignment_revision=2),
        binding(target_origin="https://other.epmdemo.xyz"),
    ):
        with pytest.raises(ValueError):
            require_current_grant(
                handoff(), current, now=100, request_hash=HASH, audience="epm:owning-source:v1"
            )
    for now in (99, 300100):
        with pytest.raises(ValueError):
            require_current_grant(
                handoff(), binding(), now=now, request_hash=HASH, audience="epm:owning-source:v1"
            )


def session_receipt():
    return SessionReceipt(
        kind="issue_session",
        operation_id=ID,
        request_hash=HASH,
        binding=binding(),
        session_id=ID,
        handoff_id=ID,
        source_revision=1,
        session_generation=1,
        recorded_at=100,
        expires_at=300100,
        renewed_from_session_id=None,
    )


def test_session_receipt_never_returns_credentials_and_unknown_never_grants_result():
    receipt = session_receipt()
    for name in ("cookie", "csrf_token", "provider_cookie", "refresh_token", "session_hash"):
        with pytest.raises(ValidationError):
            SessionReceipt(**(receipt.model_dump() | {name: "secret"}))
    reference = OperationReference(
        deployment_id=ID,
        scope=SCOPE,
        kind="issue_session",
        operation_id=ID,
        idempotency_key="original",
        request_hash=HASH,
    )
    with pytest.raises(ValidationError):
        OperationOutcome(
            operation=reference,
            state=OperationState.UNKNOWN,
            revision=1,
            observed_at=100,
            result=receipt,
            action_required="check_original",
        )


def test_session_owner_is_source_and_replay_keeps_safe_original():
    payload = IssueSession(
        assignment_id=ID,
        verified_handoff_id=ID,
        source_attempt_id=ID,
        verified_grant_hash=HASH,
        expected_session_generation=1,
    )
    intent = CommandIntent(
        deployment_id=ID,
        scope=SCOPE,
        kind=payload.action,
        expected_revision=1,
        access_epoch=1,
        payload=payload,
    )
    command = SourceCommand(
        operation_id=ID,
        idempotency_key="original",
        intent=intent,
        request_hash=semantic_hash(intent),
    )
    actor = ServiceAuthority(
        deployment_id=ID,
        scope=SCOPE,
        service="source",
        authenticated_channel_ref="verified-channel",
    )
    require_invocation(actor, command)
    with pytest.raises(ValueError):
        require_invocation(ServiceAuthority(**(actor.model_dump() | {"service": "admin"})), command)
    result = OperationOutcome(
        operation=command.reference(),
        state=OperationState.SUCCEEDED,
        revision=1,
        observed_at=100,
        result=session_receipt(),
    )
    assert original_result(command, result) is result
    changed = CommandIntent[IssueSession](**(intent.model_dump() | {"access_epoch": 2}))
    conflicting = SourceCommand(
        **(command.model_dump() | {"intent": changed, "request_hash": semantic_hash(changed)})
    )
    with pytest.raises(SemanticConflict):
        original_result(conflicting, result)


def test_auth_routes_only_accept_fixed_methods_and_no_runtime_dispatch():
    manifest = AuthRouteManifest(component_id=ID, artifact_sha256=HASH, private_endpoint_id=ID)
    assert manifest.routes == (
        ("GET", "/auth/start"),
        ("POST", "/auth/complete"),
        ("GET", "/auth/status"),
    )
    for routes in (
        (("HEAD", "/auth/start"),) + manifest.routes[1:],
        (("GET", "/api/*"),) + manifest.routes[1:],
    ):
        with pytest.raises(ValidationError):
            AuthRouteManifest(**(manifest.model_dump() | {"routes": routes}))
    parent = OperationReference(
        deployment_id=ID,
        scope=SCOPE,
        kind="provision",
        operation_id=ID,
        idempotency_key="original",
        request_hash=HASH,
    )
    effect = EffectIdentity(
        parent=parent, binding_id=ID, resource_generation=1, kind="apply_auth_routes", slot="auth"
    )
    request = ApplyAuthRoutes(
        effect=effect,
        access_epoch=1,
        expected_ingress_revision=1,
        manifest_ref="auth-source-v1",
        manifest_sha256=HASH,
    )
    assert request.effect.child_id() == effect.child_id()
    with pytest.raises(ValidationError):
        ApplyAuthRoutes(**(request.model_dump() | {"hostname": "injected.invalid"}))


def ready_routes(**changes):
    return AuthRouteObservation(
        **(
            dict(
                binding_id=ID,
                resource_generation=1,
                access_epoch=1,
                ingress_revision=1,
                desired_state="held",
                auth_route_state="ready",
                auth_access_epoch=1,
                auth_manifest_ref="auth-source-v1",
                auth_manifest_sha256=HASH,
                auth_operation_id=ID,
                auth_verified_at=100,
            )
            | changes
        )
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"desired_state": "blocked"},
        {"auth_access_epoch": 2},
        {"auth_manifest_sha256": None},
        {"auth_operation_id": None},
        {"auth_verified_at": None},
        {"auth_route_state": "closed"},
    ],
)
def test_auth_ready_requires_complete_current_nonblocked_host_receipt(changes):
    with pytest.raises(ValidationError):
        ready_routes(**changes)


def test_shared_hosts_are_not_fake_operator_assignments():
    value = SharedIdentityManifest(
        component_id=ID,
        artifact_sha256=HASH,
        private_endpoint_id=ID,
        central_origin="https://login.epmdemo.xyz",
        admin_origin="https://admin.epmdemo.xyz",
        owning_login_origin="https://login.epmdemo.xyz",
    )
    with pytest.raises(ValidationError):
        SharedIdentityManifest(
            **(value.model_dump() | {"owning_login_origin": "https://foreign.invalid"})
        )
    for routes in ((("GET", "/api/*"),), (("POST", "/auth/start"),)):
        with pytest.raises(ValidationError):
            SharedIdentityManifest(**(value.model_dump() | {"central_routes": routes}))


def test_cookie_defaults_and_realm_alias_cannot_weaken_isolation():
    cookie = IdentityCookiePolicy()
    for changes in (
        {"domain": ".epmdemo.xyz"},
        {"secure": False},
        {"http_only": False},
        {"same_site": "None"},
        {"operator": "__Host-epm-central"},
    ):
        with pytest.raises(ValidationError):
            IdentityCookiePolicy(**(cookie.model_dump() | changes))
    old = setup().realm
    changed = IdentityRealm(
        **(
            old.model_dump()
            | {
                "project_id": "different-project",
                "issuer": "https://securetoken.google.com/different-project",
                "audience": "different-project",
            }
        )
    )
    with pytest.raises(ValueError, match="cannot be remapped"):
        require_immutable_realm(old, changed)
