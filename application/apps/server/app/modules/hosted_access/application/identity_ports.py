"""H03 private evidence ports; implementations are intentionally unavailable in H03.1."""

from typing import Literal, Protocol

from pydantic import model_validator

from app.modules.hosted_access.application.identity_evidence import (
    HandoffEvidence,
    IdentityBinding,
    ManagedObservation,
    SessionObservationGrant,
    SessionReceipt,
    SourceBindingAssertion,
)
from app.platform.hosted_contracts.operations import OperationReference
from app.platform.hosted_contracts.values import Contract, RequestHash


class VerifiedEmailLink(Contract):
    """Returned only by recognized backend code completion, never browser token input."""

    method: Literal["email_link"] = "email_link"
    managed: ManagedObservation
    reserved_code_hash: RequestHash

    @model_validator(mode="after")
    def recognized_method(self):
        if self.managed.method != self.method:
            raise ValueError("Email completion must retain recognized email-link provenance.")
        return self


class PrivateIdentityPort(Protocol):
    """Verify signature + current owner records, not just the supplied model shape.

    Five-second bounded transport, outside SQLite writers. Source binding is inspected
    at the source owner; central redemption is reserved before source issuance. Unknown
    replies require original-result reconciliation, never a new bearer from a receipt.
    """

    def pair(self, assertion: SourceBindingAssertion) -> OperationReference: ...
    def redeem(self, handoff: HandoffEvidence) -> OperationReference: ...
    def acknowledge(self, receipt: SessionReceipt) -> None: ...
    def observe(self, binding: IdentityBinding) -> SessionObservationGrant: ...
    def original(self, reference: OperationReference) -> SessionReceipt | None: ...


class RateAdmissionPort(Protocol):
    """Durable atomic reservation across workers/restart, no raw recipient/IP keys.

    The central owner retains bounded buckets and cleanup batches; checks destination/
    hour, network/hour and deployment/day together before a send. Key rotation checks
    both current and previous active-window digests. A timeout is not permission to
    send; reserved/unknown sends count. H03.3 supplies the adapter.
    """

    def reserve_email(
        self, email: str, network: str, operation: OperationReference
    ) -> Literal["reserved", "throttled", "unknown"]:
        """Derive rotating digests from trusted transient destination/ingress inputs."""
        ...

    def reserve(
        self,
        destination_hash: RequestHash,
        network_hash: RequestHash,
        operation: OperationReference,
    ) -> Literal["reserved", "throttled", "unknown"]: ...
