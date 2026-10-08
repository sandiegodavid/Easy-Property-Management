"""Read-only command outcomes on a composition owner's existing snapshot."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CommandResult:
    target_id: str
    revision: int
    status: str | None


@dataclass(frozen=True)
class CommandOutcome:
    operation_id: str
    action: str
    source_id: str
    request_fingerprint: str
    result: CommandResult


class CommandRecoveryReader(Protocol):
    def outcome(self, connection, key: str, *, family: str) -> CommandOutcome | None: ...
    def state(self, connection, source_id: str) -> Mapping | None: ...


class RelatedCommandRecoveryReader(CommandRecoveryReader, Protocol):
    def related_state(self, connection, kind: str, target_id: str) -> Mapping | None: ...
