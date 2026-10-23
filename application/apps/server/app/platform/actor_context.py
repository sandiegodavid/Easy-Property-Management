"""Provider-neutral trusted invocation identity; never populated from business payloads."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class OperatorActor:
    reference: str
    workspace_id: str
    session_reference: str | None = None
    edit_lease: str | None = None

    def __post_init__(self):
        for value in (self.reference, self.workspace_id):
            if str(UUID(value)) != value:
                raise ValueError("Operator identity must use canonical UUIDs.")


_operator_actor: ContextVar[OperatorActor | None] = ContextVar("operator_actor", default=None)


def current_operator_actor() -> OperatorActor | None:
    return _operator_actor.get()


@contextmanager
def operator_actor_scope(actor: OperatorActor):
    """Task-local scope also copied by the standard threadpool invocation boundary."""
    token = _operator_actor.set(actor)
    try:
        yield
    finally:
        _operator_actor.reset(token)
