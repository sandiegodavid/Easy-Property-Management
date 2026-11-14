"""Dependency-aware H03 expiry cleanup; no cross-store calls or implied remote absence."""

from dataclasses import dataclass
import json

from sqlalchemy import Connection
from sqlalchemy.exc import IntegrityError

from app.modules.hosted_access.application.identity_setup import DAY
from app.platform.hosted_contracts.values import CanonicalId, EpochMillis
from app.platform.hosted_schema import HostedSchemaError
from app.platform.schema_resources import HostedStore
from pydantic import TypeAdapter

MAX_CANDIDATES = 100


@dataclass(frozen=True)
class CleanupResult:
    examined: int
    deleted: int


# IDs, predicates and dependency probes are code-owned, never caller SQL. Cross-store
# results are retained until a recorded maximum validity deadline has passed. Unknown
# local commands and redeeming reservations are always retained, regardless of age.
ADMIN_RULES = (
    (
        "admin_sessions",
        "session_hash",
        "expires_at<=:cutoff AND NOT EXISTS (SELECT 1 FROM managed_identity_sessions m WHERE m.managed_session_id=t.managed_session_id AND m.remembered_until>:now)",
    ),
    (
        "email_continuations",
        "continuation_id",
        "state IN ('completed','rejected','expired') AND expires_at<=:cutoff AND NOT EXISTS (SELECT 1 FROM managed_identity_sessions m WHERE m.managed_session_id=t.managed_session_id AND m.remembered_until>:now) AND NOT EXISTS (SELECT 1 FROM identity_commands c WHERE c.state IN ('pending','unknown') AND (c.attempt_id=t.original_attempt_id OR c.attempt_id=t.replacement_attempt_id OR c.managed_session_id=t.managed_session_id))",
    ),
    (
        "login_handoffs",
        "handoff_id",
        "state IN ('redeemed','expired') AND expires_at<=:cutoff AND NOT EXISTS (SELECT 1 FROM email_continuations e WHERE e.handoff_id=t.handoff_id) AND NOT EXISTS (SELECT 1 FROM managed_identity_sessions m WHERE m.managed_session_id=t.managed_session_id AND m.remembered_until>:now) AND NOT EXISTS (SELECT 1 FROM identity_commands c WHERE c.operation_id=t.identity_operation_id AND c.state IN ('pending','unknown'))",
    ),
    (
        "identity_commands",
        "operation_id",
        "state IN ('succeeded','rejected') AND updated_at<=:cutoff AND NOT EXISTS (SELECT 1 FROM login_handoffs h WHERE h.identity_operation_id=t.operation_id) AND NOT EXISTS (SELECT 1 FROM managed_identity_sessions m WHERE m.managed_session_id=t.managed_session_id AND m.remembered_until>:now)",
    ),
    (
        "login_attempts",
        "attempt_id",
        "state IN ('completed','failed','superseded','expired') AND expires_at<=:cutoff AND NOT EXISTS (SELECT 1 FROM login_handoffs h WHERE h.attempt_id=t.attempt_id) AND NOT EXISTS (SELECT 1 FROM identity_commands c WHERE c.attempt_id=t.attempt_id) AND NOT EXISTS (SELECT 1 FROM email_continuations e WHERE e.original_attempt_id=t.attempt_id OR e.replacement_attempt_id=t.attempt_id) AND NOT EXISTS (SELECT 1 FROM managed_identity_sessions m WHERE m.managed_session_id IN (t.parent_managed_session_id,t.completed_managed_session_id) AND m.remembered_until>:now)",
    ),
    (
        "managed_identity_sessions",
        "managed_session_id",
        "provider_valid_until<=:cutoff AND remembered_until<=:cutoff AND NOT EXISTS (SELECT 1 FROM login_attempts a WHERE a.parent_managed_session_id=t.managed_session_id) AND NOT EXISTS (SELECT 1 FROM login_attempts a WHERE a.completed_managed_session_id=t.managed_session_id) AND NOT EXISTS (SELECT 1 FROM identity_commands c WHERE c.managed_session_id=t.managed_session_id) AND NOT EXISTS (SELECT 1 FROM login_handoffs h WHERE h.managed_session_id=t.managed_session_id) AND NOT EXISTS (SELECT 1 FROM email_continuations e WHERE e.managed_session_id=t.managed_session_id) AND NOT EXISTS (SELECT 1 FROM admin_sessions s WHERE s.managed_session_id=t.managed_session_id)",
    ),
)
SOURCE_RULES = (
    ("source_recent_challenges", "challenge_id", "expires_at<=:cutoff"),
    (
        "access_sessions",
        "session_id",
        "expires_at<=:cutoff AND remembered_until<=:cutoff AND NOT EXISTS (SELECT 1 FROM access_sessions child WHERE child.renewed_from_session_id=t.session_id) AND NOT EXISTS (SELECT 1 FROM draft_leases d WHERE d.session_hash=t.session_hash) AND NOT EXISTS (SELECT 1 FROM source_login_attempts a WHERE a.handoff_id=t.handoff_id AND a.state='redeeming') AND NOT EXISTS (SELECT 1 FROM source_login_attempts a WHERE a.renewal_session_id=t.session_id) AND NOT EXISTS (SELECT 1 FROM source_recent_challenges c WHERE c.session_id=t.session_id)",
    ),
    (
        "source_login_attempts",
        "attempt_id",
        "state IN ('completed','expired') AND expires_at<=:cutoff AND NOT EXISTS (SELECT 1 FROM access_sessions s WHERE s.handoff_id=t.handoff_id)",
    ),
)


def cleanup_identity(
    connection: Connection,
    store: HostedStore,
    *,
    now: int,
    limit: int = MAX_CANDIDATES,
    reconciled_handoffs: tuple[str, ...] = (),
    reconciled_continuations: tuple[str, ...] = (),
) -> CleanupResult:
    """At most 100 candidates total, with dependency recheck in the same write.

    No state transition, remote lookup, FK rewriting, cascade, receipt/audit deletion
    or unfinished-form deletion. Unknown/reserved outcomes need owning reconciliation.
    Reconciled flow IDs must be supplied only from authenticated owning observations
    taken outside this writer; omission/unavailability retains logical source references.
    The owning worker validates schema before entering its immediate transaction.
    It may repeat passes as local children retire; unavailable remote results cannot
    be converted to terminal state here. Caller owns commit/rollback.
    """
    TypeAdapter(EpochMillis).validate_python(now)
    for identities in (reconciled_handoffs, reconciled_continuations):
        TypeAdapter(tuple[CanonicalId, ...]).validate_python(identities)
        if len(identities) > MAX_CANDIDATES or len(set(identities)) != len(identities):
            raise ValueError("Reconciliation observations must be bounded and unique.")
    if type(limit) is not int or not 1 <= limit <= MAX_CANDIDATES:
        raise ValueError("Cleanup requires a bounded candidate limit.")
    if store not in {HostedStore.ADMIN, HostedStore.HOSTED_ACCESS}:
        raise ValueError("Cleanup requires its exact identity store owner.")
    raw = connection.connection.driver_connection
    if (
        not connection.in_transaction()
        or not raw.in_transaction
        or connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1
    ):
        raise HostedSchemaError()
    # SQLite's caller must have acquired BEGIN IMMEDIATE; a write obtains the lock
    # without changing data, preventing a deferred snapshot from racing a dependency.
    table = "identity_commands" if store == HostedStore.ADMIN else "access_sessions"
    connection.exec_driver_sql(
        f"UPDATE main.{table} SET revision=revision WHERE 0"
        if store == HostedStore.ADMIN
        else "UPDATE main.access_sessions SET last_seen_at=last_seen_at WHERE 0"
    )
    examined = deleted = 0
    values = {
        "now": now,
        "cutoff": now - DAY,
        "handoffs": json.dumps(reconciled_handoffs),
        "continuations": json.dumps(reconciled_continuations),
    }
    for table, key, predicate in ADMIN_RULES if store == HostedStore.ADMIN else SOURCE_RULES:
        if store == HostedStore.HOSTED_ACCESS and table != "source_recent_challenges":
            predicate += " AND (handoff_id IS NULL OR handoff_id IN (SELECT value FROM json_each(:handoffs)))"
            if table == "source_login_attempts":
                predicate += " AND (continuation_id IS NULL OR continuation_id IN (SELECT value FROM json_each(:continuations)))"
        remaining = limit - examined
        if remaining <= 0:
            break
        deadline = {
            "identity_commands": "updated_at",
            "managed_identity_sessions": "provider_valid_until",
        }.get(table, "expires_at")
        rows = connection.exec_driver_sql(
            f"SELECT {key} FROM main.{table} AS t WHERE {predicate} ORDER BY {deadline},{key} LIMIT :limit",
            values | {"limit": remaining},
        ).all()
        for (identity,) in rows:
            examined += 1
            try:
                with connection.begin_nested():
                    result = connection.exec_driver_sql(
                        f"DELETE FROM main.{table} AS t WHERE {key}=:identity AND {predicate}",
                        values | {"identity": identity},
                    )
                    deleted += result.rowcount
            except IntegrityError:
                # A still-referenced row remains evidence; it does not abort others.
                continue
    return CleanupResult(examined, deleted)
