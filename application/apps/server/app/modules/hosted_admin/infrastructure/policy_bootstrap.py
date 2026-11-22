"""Idempotent Free v1 storage policy bootstrap for the main Admin store."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import UUID, uuid5

from pydantic import TypeAdapter
from sqlalchemy import Connection, text

from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_contracts.values import CanonicalId, EpochMillis
from app.platform.hosted_schema import HostedSchemaError, validate_schema
from app.platform.schema_resources import HostedStore

FREE_POLICY_NAMESPACE = UUID("d4c68f27-6a4b-5e32-9b19-2f48e1a0c5d3")
FREE_V1_PLAN_CODE = "free"
FREE_V1_POLICY_VERSION = 1
FREE_V1_USABLE_BYTES = 50_000_000
FREE_V1_BACKUP_INTERVAL_SECONDS = 86_400
FREE_V1_RETAINED_NIGHTLY_POINTS = 7
FREE_V1_KEEP_WARM = 1

_CANONICAL_ID = TypeAdapter(CanonicalId)
_EPOCH_MILLIS = TypeAdapter(EpochMillis)


class FreeV1Policy(SemanticRequest):
    """Pinned Pilot 0 Free v1 storage policy values."""

    policy_id: CanonicalId
    plan_code: Literal["free"] = FREE_V1_PLAN_CODE
    policy_version: Literal[1] = FREE_V1_POLICY_VERSION
    usable_bytes: Literal[50_000_000] = FREE_V1_USABLE_BYTES
    backup_interval_seconds: Literal[86_400] = FREE_V1_BACKUP_INTERVAL_SECONDS
    retained_nightly_points: Literal[7] = FREE_V1_RETAINED_NIGHTLY_POINTS
    keep_warm: Literal[1] = FREE_V1_KEEP_WARM
    created_at: EpochMillis


def free_v1_policy_id(deployment_id: str) -> str:
    """Derive a deterministic Free v1 policy ID for one deployment."""
    canonical = _CANONICAL_ID.validate_python(deployment_id)
    return str(
        uuid5(FREE_POLICY_NAMESPACE, f"{canonical}:{FREE_V1_PLAN_CODE}:{FREE_V1_POLICY_VERSION}")
    )


def bootstrap_free_v1_policy(
    connection: Connection,
    *,
    created_at: int,
    application_directory: Path,
    policy_id: str | None = None,
) -> tuple[FreeV1Policy, bool]:
    """Ensure the pinned Free v1 row exists in main.storage_policies.

    Caller owns the SQLite write transaction; this function never commits or closes.
    Returns ``(policy, inserted)`` where ``inserted`` is True only when newly inserted.
    Raises ``HostedSchemaError`` if schema/binding is invalid or an existing Free v1
    row has drifted from the pinned values or expected policy_id.
    """
    validate_schema(connection, HostedStore.ADMIN, application_directory=application_directory)
    if not connection.connection.driver_connection.in_transaction:
        raise HostedSchemaError()

    validated_created_at = _EPOCH_MILLIS.validate_python(created_at)
    if policy_id is None:
        deployment_id = connection.execute(
            text("SELECT deployment_id FROM main.control_meta WHERE id = 1")
        ).scalar_one_or_none()
        if deployment_id is None:
            raise HostedSchemaError()
        resolved_policy_id = free_v1_policy_id(deployment_id)
    else:
        resolved_policy_id = _CANONICAL_ID.validate_python(policy_id)

    existing = (
        connection.execute(
            text(
                "SELECT policy_id, plan_code, policy_version, usable_bytes, "
                "backup_interval_seconds, retained_nightly_points, keep_warm, created_at "
                "FROM main.storage_policies "
                "WHERE plan_code = :plan_code AND policy_version = :policy_version"
            ),
            {
                "plan_code": FREE_V1_PLAN_CODE,
                "policy_version": FREE_V1_POLICY_VERSION,
            },
        )
        .mappings()
        .one_or_none()
    )
    if existing is not None:
        if (
            existing["policy_id"] != resolved_policy_id
            or existing["usable_bytes"] != FREE_V1_USABLE_BYTES
            or existing["backup_interval_seconds"] != FREE_V1_BACKUP_INTERVAL_SECONDS
            or existing["retained_nightly_points"] != FREE_V1_RETAINED_NIGHTLY_POINTS
            or existing["keep_warm"] != FREE_V1_KEEP_WARM
        ):
            raise HostedSchemaError()
        return FreeV1Policy(**dict(existing)), False

    seed = FreeV1Policy(policy_id=resolved_policy_id, created_at=validated_created_at)
    connection.execute(
        text(
            "INSERT INTO main.storage_policies ("
            "policy_id, plan_code, policy_version, usable_bytes, "
            "backup_interval_seconds, retained_nightly_points, keep_warm, created_at"
            ") VALUES ("
            ":policy_id, :plan_code, :policy_version, :usable_bytes, "
            ":backup_interval_seconds, :retained_nightly_points, :keep_warm, :created_at"
            ")"
        ),
        seed.model_dump(),
    )
    return seed, True
