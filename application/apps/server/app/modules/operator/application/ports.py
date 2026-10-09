"""OPS persistence and runtime ports; no database connection reaches use cases."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeVar, TypedDict, Unpack

from app.modules.operator.domain.models import Preferences
from app.modules.portfolio.application.directory_ports import PropertyDirectoryQuery
from app.modules.finance.application.money_models import MoneyQuery, MoneySummary
from app.modules.tasks.application.ports import TaskParentPreview
from app.modules.portfolio.application.owner_read_ports import OwnerDirectoryQuery, PortfolioSubject
from app.platform.context_reads import ReadPage, ReadWindow
from app.platform.metadata_search import SearchTerm
from app.modules.operator.application.search_ports import SearchDefinition
from app.platform.coverage import CoverageSubject, CoverageFacts
from app.platform.command_recovery import CommandRecoveryReader

Result = TypeVar("Result")


@dataclass(frozen=True)
class RecoveryBinding:
    source_kind: str | None
    action: str
    family: str
    reader: CommandRecoveryReader
    fingerprint: Callable[[str | None, dict, str], str]
    result_kind: str
    related_state: Callable[[object, str, str], Mapping | None] | None = None
    fingerprint_payload: Callable[[object, str, dict], dict] | None = None

    @property
    def receipt_action(self):
        if self.family == "intake":
            return {
                "import": "admit",
                "dismiss": "attention_transition",
                "reopen": "attention_transition",
            }.get(self.action, self.action)
        if self.family == "issue" and self.action in {
            "start",
            "return_to_open",
            "resolve",
            "cancel",
            "reopen",
        }:
            return "transition"
        return self.action


class OperatorAuditChange(TypedDict):
    entity_type: str
    entity_id: str
    action: str
    before: Mapping | None
    after: Mapping
    correlation_id: str
    occurred_at: datetime


@dataclass(frozen=True)
class RuntimeIdentity:
    state: str
    workspace_id: str | None
    epoch: str
    can_write: bool
    reason_code: str | None = None


class RecoveryReferences(Protocol):
    def validate(self, connection, value: Mapping) -> str: ...
    def attempt_fingerprint(self, value: Mapping, key: str, *, connection=None) -> str: ...
    def resolve_attempt(
        self,
        connection,
        form_key: str,
        key: str,
        request_fingerprint: str,
        *,
        source_id: str | None = None,
    ) -> Mapping | None: ...


class OperatorTransaction(Protocol):
    def coverage_page(self, subject: PortfolioSubject, window: ReadWindow) -> ReadPage: ...
    def coverage_previews(
        self,
        kind: str,
        ids: list[str],
        query: PropertyDirectoryQuery | OwnerDirectoryQuery,
        *,
        as_of: datetime,
    ) -> Mapping[str, ReadPage]: ...
    def coverage_facts(
        self, subject: CoverageSubject, area: str, *, as_of: datetime
    ) -> CoverageFacts | None: ...
    def coverage_review(self, subject: CoverageSubject, area: str) -> Mapping | None: ...
    def coverage_operation(self, key: str) -> Mapping | None: ...
    def insert_coverage_review(self, value: Mapping) -> None: ...
    def search_sources(self) -> tuple[SearchDefinition, ...]: ...
    def search_group(self, kind: str, term: SearchTerm, window: ReadWindow) -> ReadPage: ...
    def owner_directory(
        self, query: OwnerDirectoryQuery, *, as_of: datetime, after: tuple[str, str] | None
    ) -> ReadPage: ...
    def context_identity(self, subject: PortfolioSubject) -> Mapping | None: ...
    def context_collection(
        self, section: str, subject: PortfolioSubject, window: ReadWindow
    ) -> ReadPage: ...
    def context_money(
        self,
        subject: PortfolioSubject,
        query: MoneyQuery,
        *,
        as_of: datetime,
        identity: tuple[str, str],
    ) -> MoneySummary: ...
    def money_summary(
        self, query: MoneyQuery, *, as_of: datetime, identity: tuple[str, str]
    ) -> MoneySummary: ...
    def task_previews(
        self, entity_type: str, entity_ids: list[str], *, as_of: datetime, limit: int = 10
    ) -> Mapping[str, TaskParentPreview]: ...
    def property_calendar_signature(self, as_of: datetime) -> str: ...
    def property_directory(
        self, query: PropertyDirectoryQuery, *, as_of: datetime, after: tuple[str, str] | None
    ) -> tuple[int, list[Mapping]]: ...
    def source_marker(self) -> str: ...
    def preferences(self) -> Preferences: ...
    def save_preferences(self, value: Preferences) -> None: ...
    def operation(self, key: str) -> Mapping | None: ...
    def insert_operation(self, value: Mapping) -> None: ...
    def recovery(self, record_id: str) -> Mapping | None: ...
    def save_recovery(self, value: Mapping) -> None: ...
    def active_recovery_count(self) -> int: ...
    def recovery_page(
        self, *, limit: int, after: tuple[str, str] | None
    ) -> tuple[int, list[Mapping]]: ...
    def expired_recovery(self, now: str, limit: int) -> list[Mapping]: ...
    def validate_recovery(self, value: Mapping) -> str: ...
    def attempt_fingerprint(self, value: Mapping, key: str) -> str: ...
    def resolve_attempt(self, value: Mapping) -> Mapping | None: ...
    def record_change(self, **change: Unpack[OperatorAuditChange]) -> None: ...


class OperatorUnitOfWork(Protocol):
    def read(self, operation: Callable[[OperatorTransaction], Result]) -> Result: ...
    def write(self, operation: Callable[[OperatorTransaction], Result]) -> Result: ...
