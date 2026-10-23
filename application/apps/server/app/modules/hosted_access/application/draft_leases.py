"""Transient edit authority; owning recovery revisions still govern saved content."""

from datetime import UTC, datetime
from typing import Callable, Mapping, Protocol

from app.modules.hosted_access.application.service import token_hash
from app.modules.hosted_access.domain.models import HostedAccessError, HostedActor


class DraftLeaseStore(Protocol):
    def claim(
        self,
        record_id: str,
        actor: HostedActor,
        proof: str,
        *,
        now: datetime,
        takeover: bool,
        renew: bool,
        check_revision: Callable[[], None],
    ) -> Mapping[str, float]: ...


class HostedDraftLeaseService:
    def __init__(self, store: DraftLeaseStore, revision, *, now=None):
        self.store, self.revision = store, revision
        self.now = now or (lambda: datetime.now(UTC))

    def claim(self, record_id, actor, *, token, expected_revision, takeover=False, renew=False):
        def check_revision():
            if self.revision(record_id) != expected_revision:
                raise HostedAccessError(
                    "hosted_draft_revision_conflict",
                    "Read and review the current saved form first.",
                    409,
                )

        return self.store.claim(
            record_id,
            actor,
            token_hash(token),
            now=self.now(),
            takeover=takeover,
            renew=renew,
            check_revision=check_revision,
        )
