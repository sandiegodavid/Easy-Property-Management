"""Owning source observations required by central login composition."""

from typing import Protocol
from pydantic import SecretStr
from app.modules.hosted_access.application.identity_evidence import (
    RenewalLineage,
    SourceBindingAssertion,
)
from pydantic import model_validator


from app.modules.hosted_access.application.identity_setup import HttpsOrigin
from app.modules.hosted_access.application.identity_states import (
    ReturnPath,
    SourceLoginAttemptState,
)
from app.platform.hosted_contracts.values import (
    CanonicalId,
    Contract,
    EpochMillis,
    RequestHash,
    Revision,
    Reference,
)


class SourceLoginContext(Contract):
    """Returned after authenticating the source owner and its current browser attempt."""

    operator_id: CanonicalId
    assignment_revision: Revision
    access_epoch: Revision
    target_origin: HttpsOrigin
    source_attempt_id: CanonicalId
    source_browser_hash: RequestHash
    return_path: ReturnPath
    expires_at: EpochMillis
    invitation_id: CanonicalId | None = None
    invitation_hash: RequestHash | None = None
    renewal: RenewalLineage | None = None

    @model_validator(mode="after")
    def invitation_proof(self):
        if (self.invitation_id is None) != (self.invitation_hash is None):
            raise ValueError("Invitation proof requires both its ID and verified capability hash.")
        return self


class CentralSourcePort(Protocol):
    def resolve_start(self, flow_id: str, *, origin_id: str | None = None) -> SourceLoginContext:
        """Verify owning-channel proof, registered origin, current fences and expiry."""
        ...

    def inspect_start(self, operator_id: str, source_attempt_id: str) -> SourceLoginContext:
        """Read the registered source's retained attempt over the authenticated owner channel."""
        ...

    def current(self, context: SourceLoginContext) -> None:
        """Reject changed source binding, epoch, generation, origin or attempt."""
        ...


class ClaimReadinessPort(Protocol):
    def ready(self, operator_id: str, access_epoch: int) -> bool: ...


class UnavailableClaimReadiness:
    def ready(self, operator_id: str, access_epoch: int) -> bool:
        return False


class ClaimSourceReceipt(Contract):
    operation_id: CanonicalId
    operator_id: CanonicalId
    access_epoch: Revision
    receipt_ref: Reference


class SourceClaimPort(Protocol):
    def claim(
        self, *, operation_id: str, operator_id: str, issuer: str, subject: str, access_epoch: int
    ) -> ClaimSourceReceipt: ...
    def original(self, operation_id: str) -> ClaimSourceReceipt | None: ...


class UnavailableSourceClaim:
    def claim(self, **values):
        from app.modules.hosted_access.application.managed_provider import ProviderUnavailable

        raise ProviderUnavailable()

    def original(self, operation_id):
        from app.modules.hosted_access.application.managed_provider import ProviderUnavailable

        raise ProviderUnavailable()


class ContinuationSourcePort(Protocol):
    def verify_pairing(
        self, assertion: SecretStr
    ) -> tuple[SourceBindingAssertion, SourceLoginAttemptState]:
        """Verify signature and nonce, then inspect the current owning source attempt.

        The owner must also verify the complete binding against its current
        registration. Reinspection of the same signed assertion is read-only.
        """
        ...
