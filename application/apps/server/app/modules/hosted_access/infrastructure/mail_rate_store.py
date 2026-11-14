"""Central durable mail admission; provider work starts only after reserve commits.

Use reserve_email with server-derived network identity and protected current/previous
keys. Hash-only callers must inject a trusted alias provider during rotation. Keep
previous keys for the full hourly window; never accept browser-selected aliases.
"""

from collections.abc import Callable
import hmac
import time
from typing import Literal

from pydantic import TypeAdapter
from sqlalchemy import MetaData, Table, and_, func, or_, select, update
from sqlalchemy.exc import DBAPIError

from app.modules.hosted_access.application.identity_setup import DAY, HOUR, MINUTE
from app.modules.hosted_access.application.managed_provider import email_key
from app.platform.hosted_contracts.operations import OperationReference, SemanticConflict
from app.platform.hosted_contracts.values import RequestHash
from app.platform.sqlite_engine import immediate_transaction

RETENTION_MS = DAY + HOUR
HASH = TypeAdapter(RequestHash)
Admission = Literal["reserved", "throttled", "unknown"]
Aliases = Callable[[str, str], tuple[tuple[str, ...], tuple[str, ...]]]


class SQLiteMailRateStore:
    """One owning Admin DB. Lost/failed provider replies never refund a reservation.

    Cleanup redacts expired bucket digests, retaining operation tombstones forever:
    OperationReference has no expiry, so deleting them would authorize old replays.
    The trusted caller owns canonical request hashes including the send destination.
    """

    def __init__(
        self,
        engine,
        deployment_id: str,
        *,
        keys: tuple[bytes, ...],
        daily_limit: int = 100,
        clock: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        alias_provider: Aliases | None = None,
    ):
        if (
            not 1 <= len(keys) <= 2
            or any(not isinstance(key, bytes) or len(key) < 32 for key in keys)
            or len(set(keys)) != len(keys)
            or type(daily_limit) is not int
            or daily_limit <= 0
        ):
            raise ValueError("Protected current/previous keys and positive daily limit required.")
        self.engine, self.deployment_id = engine, deployment_id
        self.keys, self.daily_limit, self.clock = keys, daily_limit, clock
        self.alias_provider = alias_provider
        self.table = Table("identity_mail_reservations", MetaData(), autoload_with=engine)

    def reserve_email(self, email: str, network: str, operation: OperationReference) -> Admission:
        """Transient raw inputs from trusted server routing; no email, IP or link stored.

        Network must be the ingress owner's canonical network identity, never a
        browser-supplied header. Email preserves local case/dots/plus semantics.
        """
        if not isinstance(network, str) or not network or len(network) > 254:
            raise ValueError("Canonical ingress network identity required.")
        destination = email_key("mail", email)
        destinations = self._hashes("destination", destination)
        networks = self._hashes("network", network)
        return self._reserve(destinations, networks, operation)

    def _hashes(self, domain: str, value: str) -> tuple[str, ...]:
        message = f"{self.deployment_id}\0{domain}\0{value}".encode()
        return tuple(hmac.digest(key, message, "sha256").hex() for key in self.keys)

    def reserve(
        self,
        destination_hash: RequestHash,
        network_hash: RequestHash,
        operation: OperationReference,
    ) -> Admission:
        destination_hash, network_hash = (
            HASH.validate_python(destination_hash),
            HASH.validate_python(network_hash),
        )
        if self.alias_provider is not None:
            destinations, networks = self.alias_provider(destination_hash, network_hash)
            if destinations[0] != destination_hash or networks[0] != network_hash:
                raise ValueError("Trusted aliases must start with the current digest.")
        elif len(self.keys) > 1:
            raise ValueError("Rotation requires trusted aliases or reserve_email.")
        else:
            destinations, networks = (destination_hash,), (network_hash,)
        return self._reserve(destinations, networks, operation)

    def _reserve(self, destinations, networks, operation) -> Admission:
        operation = OperationReference.model_validate(operation)
        if operation.deployment_id != self.deployment_id:
            raise ValueError("Mail admission belongs to another deployment.")
        for aliases in (destinations, networks):
            if not 1 <= len(aliases) <= 2:
                raise ValueError("Only current and previous digests are accepted.")
            for digest in aliases:
                HASH.validate_python(digest)
        scope = operation.scope.model_dump_json()
        table = self.table
        try:
            with immediate_transaction(self.engine) as conn:
                now = self.clock()
                owner = table.c.deployment_id == self.deployment_id
                same_key = and_(
                    table.c.scope == scope,
                    table.c.kind == operation.kind,
                    table.c.idempotency_key == operation.idempotency_key,
                )
                rows = (
                    conn.execute(
                        select(table).where(
                            owner, or_(same_key, table.c.operation_id == operation.operation_id)
                        )
                    )
                    .mappings()
                    .all()
                )
                if rows:
                    for row in rows:
                        if (
                            row["scope"] != scope
                            or row["kind"] != operation.kind
                            or row["idempotency_key"] != operation.idempotency_key
                            or row["request_hash"] != operation.request_hash
                        ):
                            raise SemanticConflict()
                    return "unknown"
                # Three indexed rolling windows; a row counts once across key aliases.
                destination = and_(owner, table.c.destination_hash.in_(destinations))
                network = and_(owner, table.c.network_hash.in_(networks))
                recent = table.c.reserved_at > now - HOUR
                last, count = conn.execute(
                    select(func.max(table.c.reserved_at), func.count()).where(destination, recent)
                ).one()
                if (last is not None and now - last < MINUTE) or count >= 5:
                    return "throttled"
                if conn.scalar(select(func.count()).where(network, recent)) >= 20:
                    return "throttled"
                if (
                    conn.scalar(select(func.count()).where(owner, table.c.reserved_at > now - DAY))
                    >= self.daily_limit
                ):
                    return "throttled"
                conn.execute(
                    table.insert().values(
                        deployment_id=self.deployment_id,
                        scope=scope,
                        kind=operation.kind,
                        operation_id=operation.operation_id,
                        idempotency_key=operation.idempotency_key,
                        request_hash=operation.request_hash,
                        destination_hash=destinations[0],
                        network_hash=networks[0],
                        reserved_at=now,
                        redact_after=now + RETENTION_MS,
                    )
                )
            return "reserved"
        except DBAPIError:
            # Includes ambiguous commit and busy/unavailable stores; never grant a send.
            return "unknown"

    def cleanup(self) -> int:
        """Redact at most 100 expired buckets; preserve immutable replay evidence."""
        table = self.table
        with immediate_transaction(self.engine) as conn:
            now = self.clock()
            eligible = and_(
                table.c.deployment_id == self.deployment_id,
                table.c.redact_after <= now,
                table.c.destination_hash.is_not(None),
            )
            ids = (
                select(table.c.operation_id)
                .where(eligible)
                .order_by(table.c.redact_after, table.c.operation_id)
                .limit(100)
            )
            result = conn.execute(
                update(table)
                .where(eligible, table.c.operation_id.in_(ids))
                .values(destination_hash=None, network_hash=None)
            )
            return result.rowcount
