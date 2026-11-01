"""Persistent upgrade fence, independent of session lifetime and access activation."""

from datetime import UTC, datetime
import json
import math

import sqlalchemy as sa

from app.modules.hosted_access.application.maintenance import MaintenanceCommand, MaintenanceState
from app.modules.hosted_access.application.admin_commands import deployment_fingerprint
from app.modules.hosted_access.domain.models import HostedAccessError
from app.platform.sqlite_engine import immediate_transaction


def initialize_maintenance(operations, connection):
    operations.create_table(
        "hosted_maintenance",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("state", sa.Text, nullable=False),
        sa.CheckConstraint("id=1"),
    )
    operations.create_table(
        "hosted_maintenance_receipt",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("request", sa.Text, nullable=False),
        sa.Column("before_state", sa.Text, nullable=False),
        sa.Column("after_state", sa.Text, nullable=False),
        sa.Column("recorded", sa.Float, nullable=False),
    )
    initial = MaintenanceState(
        revision=0, generation=0, binding=0, fence=0, was_active=False
    ).model_dump_json()
    connection.exec_driver_sql("INSERT INTO hosted_maintenance VALUES (1,?)", (initial,))
    for verb in ("UPDATE", "DELETE"):
        connection.exec_driver_sql(
            f"CREATE TRIGGER maintenance_receipt_no_{verb.lower()} BEFORE {verb} ON hosted_maintenance_receipt "
            "BEGIN SELECT RAISE(ABORT,'Immutable maintenance audit and receipt'); END"
        )


def blocked():
    return HostedAccessError(
        "hosted_upgrade_in_progress", "Upgrade in progress. Your unfinished work is preserved.", 503
    )


class MaintenanceGate:
    def __init__(self, store):
        self.store = store
        metadata = sa.MetaData()
        self.state = sa.Table("hosted_maintenance", metadata, autoload_with=store.engine)
        self.receipts = sa.Table("hosted_maintenance_receipt", metadata, autoload_with=store.engine)

    def current(self, connection=None):
        if connection is None:
            with self.store.engine.connect() as opened:
                return self.current(opened)
        return MaintenanceState.model_validate_json(
            connection.scalar(sa.select(self.state.c.state))
        )

    def require_open(self, connection):
        if self.current(connection).owner is not None:
            raise blocked()

    def receipt(self, command, connection):
        row = (
            connection.execute(sa.select(self.receipts).where(self.receipts.c.id == command.id))
            .mappings()
            .one_or_none()
        )
        if row is not None and row["request"] != command.model_dump_json():
            raise HostedAccessError(
                "hosted_maintenance_identity_conflict", "This upgrade command changed.", 409
            )
        return MaintenanceState.model_validate_json(row["after_state"]) if row else None

    def execute(self, command: MaintenanceCommand, now=None):
        now = now or datetime.now(UTC)
        with immediate_transaction(self.store.engine) as connection:
            original = self.receipt(command, connection)
            if original is not None:
                return original
            before = self.current(connection)
            operator = connection.execute(sa.select(self.store.operator)).mappings().one()
            if (
                before.revision,
                operator["admin_revision"],
                operator["binding_revision"],
                operator["admin_fence"],
            ) != (
                command.expected_revision,
                command.expected_admin_revision,
                command.expected_binding_revision,
                command.expected_fence,
            ):
                raise HostedAccessError(
                    "hosted_maintenance_conflict",
                    "Review the current upgrade and access state.",
                    409,
                )
            if command.action == "pause":
                if operator["binding_digest"] != deployment_fingerprint(self.store.deployment):
                    raise HostedAccessError(
                        "hosted_maintenance_binding_changed",
                        "Review the current deployment binding.",
                        409,
                    )
                if before.owner is not None:
                    raise HostedAccessError(
                        "hosted_maintenance_owned",
                        "Another maintenance operation owns this instance.",
                        409,
                    )
                generation = operator["generation"] + int(command.revoke_sessions)
                if command.revoke_sessions:
                    connection.execute(
                        sa.update(self.store.operator).values(
                            generation=generation, not_before=now.timestamp()
                        )
                    )
                after = MaintenanceState(
                    revision=before.revision + 1,
                    owner=command.owner,
                    release=command.release,
                    generation=generation,
                    binding=operator["binding_revision"],
                    fence=operator["admin_fence"],
                    was_active=operator["active"],
                )
            else:
                if before.owner != command.owner:
                    raise HostedAccessError(
                        "hosted_maintenance_owner_conflict",
                        "Only this upgrade can remove its pause.",
                        409,
                    )
                eligible = (
                    before.was_active
                    and operator["binding_digest"] == deployment_fingerprint(self.store.deployment)
                    and operator["active"]
                    and before.generation == operator["generation"]
                    and before.binding == operator["binding_revision"]
                    and before.fence == operator["admin_fence"]
                    and self.store.deployment.enabled_at <= now < self.store.deployment.expires_at
                )
                if command.restore_access and not eligible:
                    raise HostedAccessError(
                        "hosted_maintenance_access_changed",
                        "Access changed during the upgrade. Keep access paused or disabled.",
                        409,
                    )
                # Keeping disabled never mutates activation authority. A disabled
                # source may clear this gate; an active one must first be disabled
                # through its ordinary atomic access command.
                if not command.restore_access and operator["active"]:
                    raise HostedAccessError(
                        "hosted_maintenance_requires_disable",
                        "Disable access before accepting without access.",
                        409,
                    )
                after = before.model_copy(
                    update={
                        "revision": before.revision + 1,
                        "owner": None,
                        "release": command.release,
                    }
                )
            connection.execute(sa.update(self.state).values(state=after.model_dump_json()))
            connection.execute(
                self.receipts.insert().values(
                    id=command.id,
                    request=command.model_dump_json(),
                    before_state=before.model_dump_json(),
                    after_state=after.model_dump_json(),
                    recorded=now.timestamp(),
                )
            )
            return after

    def validate_retained(self):
        with self.store.engine.connect() as connection:
            prior = MaintenanceState(revision=0, generation=0, binding=0, fence=0, was_active=False)
            rows = connection.execute(sa.select(self.receipts)).mappings().all()
            ordered = sorted(rows, key=lambda row: json.loads(row["after_state"])["revision"])
            for row in ordered:
                command = MaintenanceCommand.model_validate_json(row["request"])
                before = MaintenanceState.model_validate_json(row["before_state"])
                after = MaintenanceState.model_validate_json(row["after_state"])
                if (
                    row["id"] != command.id
                    or before != prior
                    or after.revision != before.revision + 1
                    or command.expected_revision != before.revision
                    or not math.isfinite(row["recorded"])
                    or row["recorded"] < 0
                    or command.model_dump_json() != row["request"]
                    or before.model_dump_json() != row["before_state"]
                    or after.model_dump_json() != row["after_state"]
                ):
                    raise ValueError("Invalid maintenance history.")
                if command.action == "pause":
                    if (
                        before.owner is not None
                        or after.owner != command.owner
                        or after.release != command.release
                        or after.binding != command.expected_binding_revision
                        or after.fence != command.expected_fence
                    ):
                        raise ValueError("Invalid maintenance pause.")
                elif before.owner != command.owner or after != before.model_copy(
                    update={"revision": after.revision, "owner": None, "release": command.release}
                ):
                    raise ValueError("Invalid maintenance acceptance.")
                prior = after
            if self.current(connection) != prior:
                raise ValueError("Invalid maintenance tip.")
