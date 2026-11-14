"""Administrator recovery is authenticated, allowlisted and never restores authority."""

from uuid import uuid4

import pytest

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.application.recovery_publication import RecoveryPublicationError
from app.modules.hosted_access.infrastructure.recovery_bundle import (
    RecoveryBundle,
    open_bundle,
    seal_bundle,
)


def test_bundle_round_trip_excludes_usable_authority_and_rejects_tampering(
    deployment_values, tmp_path
):
    deployment = HostedDeployment.model_validate(deployment_values)
    bundle = RecoveryBundle(
        deployment=deployment,
        approvedSubjectReference="synthetic-subject",
        pendingSubjectReferences=[],
    )
    output = tmp_path / "administrator.epm-recovery"
    passphrase = "separate administrator recovery phrase"
    seal_bundle(bundle, output, passphrase)
    decoded = open_bundle(output, passphrase)
    assert decoded.approvedSubjectReference == "synthetic-subject"
    assert decoded.restorationPolicy == "fresh_enrollment_required"
    assert decoded.deployment.workspace_id == deployment.workspace_id
    serialized = decoded.model_dump_json()
    for forbidden in (
        "synthetic-session-bearer",
        "synthetic-csrf-bearer",
        "token_hash",
        "csrf_hash",
        "edit_lease",
        "secret_access_key",
    ):
        assert forbidden not in serialized
    with pytest.raises(FileExistsError):
        seal_bundle(bundle, output, passphrase)
    with pytest.raises(RecoveryPublicationError):
        open_bundle(output, "another wrong recovery phrase")
    changed = bytearray(output.read_bytes())
    changed[-1] ^= 1
    damaged = tmp_path / "tampered.epm-recovery"
    damaged.write_bytes(changed)
    with pytest.raises(RecoveryPublicationError):
        open_bundle(damaged, passphrase)
    # This serialization test supplies no usable session or legacy store.


def test_bundle_model_cannot_smuggle_secrets_or_another_restore_policy(deployment_values):
    deployment = HostedDeployment.model_validate(deployment_values)
    with pytest.raises(ValueError):
        RecoveryBundle(deployment=deployment, sessions=[{"token": str(uuid4())}])
    with pytest.raises(ValueError):
        RecoveryBundle(deployment=deployment, restorationPolicy="restore_sessions")


def test_bundle_oversized_input_is_rejected_before_decryption(tmp_path):
    source = tmp_path / "large.epm-recovery"
    source.write_bytes(b"x" * 65537)
    with pytest.raises(RecoveryPublicationError):
        open_bundle(source, "never used passphrase")
