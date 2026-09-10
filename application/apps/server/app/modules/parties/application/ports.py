"""Application ports for shared party contact lifecycle operations."""

from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from app.modules.parties.domain.models import Party, PartyContactMethod

Result = TypeVar("Result")


class ContactReferenceResolution(Protocol):
    """One explicit role-record resolution for a contact archival operation."""

    role: str
    role_record_id: str
    replacement_contact_method_id: str | None
    clear: bool


class ContactReferenceGuard(Protocol):
    role: str

    def resolve_before_archive(
        self,
        connection: Any,
        party_id: str,
        contact_method_id: str,
        resolutions: tuple[ContactReferenceResolution, ...],
        timestamp: str,
        correlation_id: str,
    ) -> tuple[ContactReferenceResolution, ...]: ...


class PartyRoleActivityGuard(Protocol):
    def conflict(self, connection: Any, party_id: str) -> str | None: ...


class PartyRoleSummaryReader(Protocol):
    """Read-only role projection supplied by the owning module."""

    def active_roles(self, party_id: str) -> set[str]: ...


class PartyTransactionOperations(Protocol):
    """Shared identity operations performed inside a caller-owned transaction."""

    def party(self, connection: Any, party_id: str) -> Party | None: ...
    def methods(self, connection: Any, party_id: str) -> list[PartyContactMethod]: ...
    def insert_party(self, connection: Any, party: Party) -> None: ...
    def insert_method(self, connection: Any, method: PartyContactMethod) -> None: ...
    def duplicate_party_ids(
        self, connection: Any, methods: list[PartyContactMethod], limit: int
    ) -> list[str]: ...


class PartyReadOperations(Protocol):
    def get_party(self, party_id: str) -> Party | None: ...
    def parties(self, party_ids: list[str]) -> dict[str, Party]: ...
    def methods_for_parties(self, party_ids: list[str]) -> dict[str, list[PartyContactMethod]]: ...
    def search(self, *, active_only: bool, search: str | None) -> list[Party]: ...


class PartyTransaction(Protocol):
    def party(self, party_id: str) -> Party | None: ...
    def methods(self, party_id: str) -> list[PartyContactMethod]: ...
    def duplicate_party_ids(self, methods: list[PartyContactMethod], limit: int) -> list[str]: ...
    def insert_party(self, item: Party) -> None: ...
    def replace_party(self, item: Party) -> None: ...
    def party_role_conflicts(self, party_id: str) -> list[str]: ...
    def insert_method(self, item: PartyContactMethod) -> None: ...
    def replace_method(self, item: PartyContactMethod) -> None: ...
    def resolve_contact_references(
        self,
        party_id: str,
        method_id: str,
        resolutions: tuple[ContactReferenceResolution, ...],
        timestamp: str,
        correlation_id: str,
    ) -> tuple[ContactReferenceResolution, ...]: ...
    def record_change(self, **change: Any) -> None: ...


class PartyUnitOfWork(Protocol):
    def write(self, operation: Callable[[PartyTransaction], Result]) -> Result: ...
    def methods(self, party_id: str) -> tuple[Party, list[PartyContactMethod]] | None: ...
