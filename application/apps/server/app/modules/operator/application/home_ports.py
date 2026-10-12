"""Typed composition boundary; source adapters share the infrastructure read transaction."""

from collections.abc import Callable
from typing import Protocol, TypeVar
from dataclasses import dataclass
from collections.abc import Mapping

from app.modules.operator.application.home_contracts import HomeScope, HomeQuery, AvailableMoney
from app.modules.operator.application.home_vocabulary import SourceKind
from app.platform.attention_reads import (
    AttentionPage,
    AttentionWindow,
    InventoryFacts,
    AttentionFact,
)
from app.modules.tasks.application.attention_ports import TaskAttentionReader
from app.modules.maintenance.application.attention_ports import MaintenanceAttentionReader
from app.modules.finance.application.attention_ports import RentAttentionReader
from app.modules.finance.application.money_ports import MoneyContextReader
from app.modules.leases.application.attention_ports import LeaseAttentionReader
from app.modules.owner_accounting.application.attention_ports import OwnerReportAttentionReader
from app.modules.owner_management.application.attention_ports import OwnerConcernAttentionReader
from app.modules.portfolio.application.attention_ports import PortfolioAttentionReader
from app.modules.operator.application.attention_ports import CoverageAttentionReader
from app.platform.attention_reads import AttentionReader
from app.modules.operator.domain.models import OperatorSectionUnavailable

Result = TypeVar("Result")


class HomeAdapterMissing(OperatorSectionUnavailable):
    """A missing configured projection is distinct from a failed source read."""


@dataclass(frozen=True)
class HomeSources:
    """Bootstrap must supply every core source plus independent scope and money readers."""

    tasks: TaskAttentionReader
    maintenance: MaintenanceAttentionReader
    rent: RentAttentionReader
    leases: LeaseAttentionReader
    reports: OwnerReportAttentionReader
    concerns: OwnerConcernAttentionReader
    coverage: CoverageAttentionReader
    portfolio: PortfolioAttentionReader
    money: MoneyContextReader

    def attention_registry(self) -> Mapping[SourceKind, AttentionReader]:
        return {
            SourceKind.TASK: self.tasks,
            SourceKind.RENT: self.rent,
            SourceKind.ISSUE: self.maintenance,
            SourceKind.APPOINTMENT: self.maintenance,
            SourceKind.LEASE: self.leases,
            SourceKind.REPORT: self.reports,
            SourceKind.CONCERN: self.concerns,
            SourceKind.COVERAGE: self.coverage,
        }

    @property
    def ready(self) -> bool:
        return (
            set(self.supported_sources()) == set(SourceKind)
            and all(
                callable(getattr(self.portfolio, method, None))
                for method in (
                    "validate_scope",
                    "calendars",
                    "inventory",
                    "inventory_spaces",
                    "attention_labels",
                )
            )
            and callable(getattr(self.money, "summary", None))
        )

    def supported_sources(self) -> tuple[SourceKind, ...]:
        supported = []
        for source, reader in self.attention_registry().items():
            methods = ("attention",)
            if source == SourceKind.TASK:
                methods += ("facts", "standalone_attention", "hydrate")
            elif source in (SourceKind.ISSUE, SourceKind.CONCERN):
                methods += ("follow_up_relations",)
            if all(callable(getattr(reader, method, None)) for method in methods):
                supported.append(source)
        return tuple(supported)


class HomeReadTransaction(Protocol):
    def supported_sources(self) -> tuple[SourceKind, ...]: ...
    def source_marker(self) -> str: ...
    def validate_scope(self, scope: HomeScope) -> None: ...
    def attention(self, source: SourceKind, window: AttentionWindow) -> AttentionPage: ...
    def hydrate_locations(
        self, facts: tuple[AttentionFact, ...], window: AttentionWindow
    ) -> tuple[AttentionFact, ...]: ...
    def inventory(self, window: AttentionWindow) -> InventoryFacts: ...
    def money(
        self, query: HomeQuery, window: AttentionWindow, *, identity: tuple[str, str]
    ) -> AvailableMoney: ...


class HomeUnitOfWork(Protocol):
    def read(self, operation: Callable[[HomeReadTransaction], Result]) -> Result:
        """One caller-owned deferred transaction for the complete composition."""
        ...
