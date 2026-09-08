"""LEASE-001 ownership rules for generic FILE-001 links."""

from __future__ import annotations

from app.modules.files.application.errors import FileError
from app.modules.files.application.ports import FileLink
from app.modules.leases.application.ports import LeaseUnitOfWork


class LeaseFileLinkValidator:
    entity_types = frozenset({"lease", "lease_termination_case"})

    _purposes = {
        "lease": frozenset({"executed_lease", "addendum", "renewal_offer", "supporting_document"}),
        "lease_termination_case": frozenset({
            "termination_request", "relocation_support", "termination_proposal",
            "signed_termination_agreement", "supporting_document",
        }),
    }

    def __init__(self, leases: LeaseUnitOfWork) -> None:
        self.leases = leases

    def validate(self, link: FileLink) -> None:
        if link.purpose not in self._purposes[link.entity_type]:
            raise FileError(f"Unsupported {link.entity_type} file purpose.")
        if link.entity_type == "lease":
            exists = self.leases.lease_view(link.entity_id) is not None
        else:
            exists = self.leases.termination_case_view(link.entity_id) is not None
        if not exists:
            raise FileError(f"The linked {link.entity_type.replace('_', ' ')} does not exist.")
