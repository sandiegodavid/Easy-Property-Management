from unittest.mock import Mock

import pytest

from app.modules.hosted_access.application.admin_admission import AdminAdmission, AdminPrincipal
from app.modules.hosted_access.application.managed_provider import ProviderDenied
from app.modules.hosted_access.tests.test_firebase_provider import NOW

pytest_plugins = ("app.modules.hosted_access.tests.test_firebase_provider",)


def test_allowlisted_google_proof_opens_factor_flow_only(provider):
    verifier, sign, _, _ = provider
    reader = Mock()
    reader.by_identity.return_value = AdminPrincipal("principal", True, 1)
    service = AdminAdmission(verifier.realm, reader)
    now = NOW * 1000
    proof = verifier.google(sign())
    assert service.require_principal(proof, now=now) == reader.by_identity.return_value
    reader.by_identity.assert_called_once_with(verifier.realm.alias, "uid")
    with pytest.raises(ProviderDenied):
        service.session_deadline(proof, now=now)
    totp = verifier.google(
        sign({"firebase": {"sign_in_provider": "google.com", "sign_in_second_factor": "totp"}}),
        admin=True,
    )
    assert service.session_deadline(totp, now=now) == (
        reader.by_identity.return_value,
        totp.expires_at,
    )
    with pytest.raises(ProviderDenied):
        service.session_deadline(totp, now=totp.authenticated_at + 900000)


@pytest.mark.parametrize("principal", [None, AdminPrincipal("principal", False, 1)])
def test_valid_google_factor_cannot_grant_admin_authority(provider, principal):
    verifier, sign, _, _ = provider
    reader = Mock()
    reader.by_identity.return_value = principal
    service = AdminAdmission(verifier.realm, reader)
    proof = verifier.google(
        sign({"firebase": {"sign_in_provider": "google.com", "sign_in_second_factor": "totp"}}),
        admin=True,
    )
    with pytest.raises(ProviderDenied):
        service.session_deadline(proof, now=NOW * 1000)


def test_session_requires_current_principal_and_fresh_status():
    from app.modules.hosted_access.application.admin_admission import require_admin_session
    from app.modules.hosted_access.application.identity_states import AdminSessionState
    from app.modules.hosted_access.tests.test_identity_states import admin_data

    session = AdminSessionState(**admin_data())
    principal = AdminPrincipal(session.principal_id, True, session.generation)
    require_admin_session(session, principal, now=session.mfa_verified_at, sensitive=True)
    with pytest.raises(ProviderDenied):
        require_admin_session(session, principal, now=session.revocation_valid_until)
    with pytest.raises(ProviderDenied):
        require_admin_session(
            session,
            AdminPrincipal(principal.principal_id, True, principal.session_generation + 1),
            now=session.mfa_verified_at,
        )
