"""Single private inventory authority; short writes around independently inspected effects."""

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import stat
from urllib.parse import urlsplit

from sqlalchemy import Connection, MetaData, Table, create_engine, func, select
from sqlalchemy.pool import NullPool

from app.modules.host_agent.application.build_inputs import PrincipalRange
from app.modules.host_agent.application.network import NetworkRecord, NetworkProjection
from app.modules.host_agent.application.ingress import IngressRecord, IngressProjection, MAX_ORIGINS
from app.modules.host_agent.application.dispatch import (
    AdmittedEffect,
    Allocation,
    EffectObservation,
    EffectReceipt,
    HostAgentDenied,
    HostAgentUnavailable,
    HostEffect,
    StoredEffect,
    ResourceLimits,
    TreeLimits,
)
from app.modules.host_agent.infrastructure.schema_store import HostMetadata
from app.platform.hosted_contracts.operations import SemanticConflict
from app.platform.hosted_contracts.semantic import canonical_bytes, semantic_hash
from app.platform.hosted_schema import validate_schema
from app.platform.schema_resources import HostedStore


class Inventory:
    """No creator/adoption path. Startup pins a private initialized store and singleton.

    One protected flock serializes agent effects across processes without a SQLite
    writer held during external work. Other writers must use this owning boundary.
    The agent is host-trusted; this does not defend against hostile host root.
    """

    def __init__(
        self,
        path: Path,
        *,
        application_directory: Path,
        identity: HostMetadata,
        uids: PrincipalRange,
        gids: PrincipalRange,
        projects: PrincipalRange,
        public_domain: str,
        system_ids,
    ):
        self.path = path
        self.application_directory = application_directory
        self.identity = identity
        self.uids, self.gids, self.projects = uids, gids, projects
        self.public_domain = public_domain
        # Protected setup supplies a full system/container identity collision probe.
        # There is no permissive NSS-only fallback or empty production identity set.
        self.system_ids = system_ids
        self._pin = self._file_identity(path)
        self._lock_path = path.with_name(path.name + ".effects.lock")
        with self.transaction(write=False):
            pass

    @staticmethod
    def _file_identity(path):
        if not path.is_absolute() or path.resolve() != path:
            raise HostAgentDenied()
        parent, info = path.parent.stat(), path.lstat()
        if (
            parent.st_uid != os.getuid()
            or stat.S_IMODE(parent.st_mode) & 0o077
            or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise HostAgentDenied()
        return info.st_dev, info.st_ino

    def _connect(self, write):
        if self._file_identity(self.path) != self._pin:
            raise HostAgentDenied()
        mode = "rw" if write else "ro"
        raw = sqlite3.connect(self.path.as_uri() + f"?mode={mode}", uri=True, isolation_level=None)
        raw.execute("PRAGMA foreign_keys=ON")
        if not write:
            raw.execute("PRAGMA query_only=ON")
        return raw

    @contextmanager
    def transaction(self, *, write=True) -> Iterator[Connection]:
        engine = create_engine(
            "sqlite://", poolclass=NullPool, creator=lambda: self._connect(write)
        )
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")
                try:
                    validate_schema(
                        connection,
                        HostedStore.HOST_INVENTORY,
                        application_directory=self.application_directory,
                    )
                    expected = {"id": 1, **self.identity.model_dump()}
                    rows = list(
                        connection.exec_driver_sql("SELECT * FROM host_identity").mappings()
                    )
                    if rows != [expected]:
                        raise HostAgentDenied()
                    yield connection
                    if write:
                        connection.commit()
                finally:
                    connection.rollback()
        finally:
            engine.dispose()

    @contextmanager
    def exclusive(self):
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
        descriptor = os.open(self._lock_path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
            ):
                raise HostAgentDenied()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise HostAgentUnavailable() from error
            yield
        finally:
            os.close(descriptor)

    @staticmethod
    def table(connection, name):
        return Table(name, MetaData(), autoload_with=connection)

    def original(self, connection, command):
        table = self.table(connection, "host_receipts")
        row = (
            connection.execute(
                select(table).where(
                    table.c.kind == command.effect.kind,
                    table.c.idempotency_key == command.effect.child_key(),
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is not None:
            retained = StoredEffect.model_validate_json(row["request_json"])
            if (
                row["request_hash"] != semantic_hash(command)
                or canonical_bytes(retained.command) != canonical_bytes(command)
                or row["operation_id"] != command.effect.child_id()
            ):
                raise SemanticConflict()
        return row

    def reserve(self, admitted: AdmittedEffect, now):
        command = admitted.command
        with self.transaction(write=False) as connection:
            original = self.original(connection, command)
            if original is not None:
                return original, None, False
        # NSS/OS/container identity probes must never run under a SQLite writer.
        occupied = self.system_ids() if command.effect.kind == "prepare_resources" else None
        with self.transaction() as connection:
            original = self.original(connection, command)
            if original is not None:
                return original, self.allocation(connection, command), False
            if command.effect.parent.deployment_id != self.identity.deployment_id:
                raise HostAgentDenied()
            binding = self._binding(connection, command)
            if command.effect.kind == "prepare_resources":
                if binding is not None:
                    raise HostAgentDenied()
                self._allocate(connection, admitted, now, occupied)
            else:
                self._current(connection, command, binding)
                self._resource_inputs(admitted, binding)
            receipt = self.table(connection, "host_receipts")
            connection.execute(
                receipt.insert().values(
                    operation_id=command.effect.child_id(),
                    parent_operation_id=command.effect.parent.operation_id,
                    idempotency_key=command.effect.child_key(),
                    request_hash=semantic_hash(command),
                    request_json=canonical_bytes(admitted.retained()).decode(),
                    binding_id=command.effect.binding_id,
                    access_epoch=command.access_epoch,
                    kind=command.effect.kind,
                    state="pending",
                    recorded_at=now,
                    revision=1,
                )
            )
            self._reserve_ingress(connection, admitted, now)
            return self.original(connection, command), self.allocation(connection, command), True

    def _binding(self, connection, command):
        table = self.table(connection, "resource_bindings")
        return (
            connection.execute(select(table).where(table.c.binding_id == command.effect.binding_id))
            .mappings()
            .one_or_none()
        )

    def _current(self, connection, command, binding):
        scope = command.effect.parent.scope
        if (
            binding is None
            or binding["operator_id"] != scope.operator_id
            or binding["workspace_id"] != scope.workspace_id
            or binding["resource_generation"] != command.effect.resource_generation
            or binding["revision"] != command.expected_revision
            or binding["state"] == "retired"
        ):
            raise HostAgentDenied()
        ingress = self.table(connection, "ingress_bindings")
        current = (
            connection.execute(select(ingress).where(ingress.c.operator_id == scope.operator_id))
            .mappings()
            .one_or_none()
        )
        if (
            current is None
            or current["binding_id"] != binding["binding_id"]
            or current["resource_generation"] != binding["resource_generation"]
        ):
            raise HostAgentDenied()
        if command.effect.kind == "apply_ingress_policy":
            if (
                command.access_epoch < current["access_epoch"]
                or command.payload.expected_ingress_revision != current["revision"]
            ):
                raise HostAgentDenied()
        elif command.access_epoch != current["access_epoch"]:
            raise HostAgentDenied()
        if (
            command.effect.kind in {"start_container", "initialize_container", "repair_runtime"}
            and current["desired_state"] == "blocked"
        ):
            raise HostAgentDenied()
        if command.effect.kind == "repair_runtime" and binding["state"] != "stopped":
            raise HostAgentDenied()
        receipts = self.table(connection, "host_receipts")
        unresolved = connection.execute(
            select(receipts.c.operation_id)
            .where(
                receipts.c.binding_id == command.effect.binding_id,
                receipts.c.state.in_(("pending", "unknown")),
            )
            .limit(1)
        ).first()
        if unresolved is not None and command.effect.kind not in {
            "stop_container",
            "apply_ingress_policy",
        }:
            raise HostAgentDenied()
        if command.effect.kind == "retire_resources" and (
            binding["state"] != "stopped"
            or current["desired_state"] != "blocked"
            or current["verified_state"] != "blocked"
            or current["verified_revision"] != current["revision"]
        ):
            raise HostAgentDenied()

    def _resource_inputs(self, admitted, binding):
        command, plan = admitted.command, admitted.plan
        if command.effect.kind in {"initialize_container", "repair_runtime"}:
            if (
                plan is None
                or plan.image_id != command.payload.image_id
                or plan.release_id != command.payload.release_id
                or plan.image_digest != binding["image_digest"]
            ):
                raise HostAgentDenied()
        elif command.effect.kind == "apply_limits":
            if plan is None or plan.limit_profile_id != command.payload.qualified_limit_profile_id:
                raise HostAgentDenied()

    def _allocate(self, connection, admitted, now, occupied):
        command, plan = admitted.command, admitted.plan
        scope = command.effect.parent.scope
        payload = command.payload
        if (
            plan is None
            or plan.image_id != payload.image_id
            or plan.release_id != payload.release_id
            or plan.capacity_profile_ref != payload.capacity_profile_ref
            or command.expected_revision != 1
        ):
            raise HostAgentDenied()
        self._validate_origin(admitted.public_origin)
        principal_table = self.table(connection, "operator_principals")
        principal = (
            connection.execute(
                select(principal_table).where(principal_table.c.operator_id == scope.operator_id)
            )
            .mappings()
            .one_or_none()
        )
        if principal is None:
            used_uids, used_gids = (set(occupied[0]), set(occupied[1]))
            used_uids |= set(connection.execute(select(principal_table.c.host_uid)).scalars())
            used_gids |= set(connection.execute(select(principal_table.c.host_gid)).scalars())
            connection.execute(
                principal_table.insert().values(
                    operator_id=scope.operator_id,
                    workspace_id=scope.workspace_id,
                    host_uid=next_id(self.uids, used_uids),
                    host_gid=next_id(self.gids, used_gids),
                    assigned_at=now,
                    revision=1,
                )
            )
        elif principal["workspace_id"] != scope.workspace_id or principal["retired_at"] is not None:
            raise HostAgentDenied()
        binding_table = self.table(connection, "resource_bindings")
        key = command.effect.binding_id
        values = dict(
            binding_id=key,
            operator_id=scope.operator_id,
            workspace_id=scope.workspace_id,
            resource_generation=command.effect.resource_generation,
            role="active",
            workspace_relative_ref="workspace:" + key,
            access_relative_ref="control:" + key,
            scratch_relative_ref="scratch:" + key,
            image_digest=plan.image_digest,
            state="allocated",
            provision_operation_id=command.effect.parent.operation_id,
            revision=1,
        )
        for tree in ("workspace", "control", "scratch"):
            limit = getattr(plan, tree)
            values.update(
                {
                    tree + "_byte_ceiling": limit.byte_ceiling,
                    tree + "_inode_ceiling": limit.inode_ceiling,
                }
            )
        connection.execute(binding_table.insert().values(**values))
        projects = self.table(connection, "project_assignments")
        used = set(connection.execute(select(projects.c.project_id)).scalars())
        for tree in ("workspace", "control", "scratch"):
            project = next_id(self.projects, used)
            used.add(project)
            connection.execute(
                projects.insert().values(
                    project_id=project,
                    binding_id=key,
                    tree_kind=tree,
                    filesystem_identity=self.identity.filesystem_identity,
                    assigned_at=now,
                )
            )

    def _validate_origin(self, value):
        parsed = urlsplit(value or "")
        host = parsed.hostname or ""
        prefix = host.removesuffix("." + self.public_domain)
        if (
            value != "https://" + host
            or not host.endswith("." + self.public_domain)
            or not prefix
            or "." in prefix
            or prefix in {"admin", "login", "www", "api"}
        ):
            raise HostAgentDenied()

    def _reserve_ingress(self, connection, admitted, now):
        command = admitted.command
        table = self.table(connection, "ingress_bindings")
        if command.effect.kind == "prepare_resources":
            scope = command.effect.parent.scope
            connection.execute(
                table.insert().values(
                    operator_id=scope.operator_id,
                    workspace_id=scope.workspace_id,
                    binding_id=command.effect.binding_id,
                    resource_generation=command.effect.resource_generation,
                    public_origin=admitted.public_origin,
                    access_epoch=command.access_epoch,
                    desired_state="held",
                    operation_id=command.effect.child_id(),
                    verified_state="unknown",
                    updated_at=now,
                    revision=1,
                )
            )
        elif command.effect.kind == "apply_ingress_policy":
            connection.execute(
                table.update()
                .where(table.c.operator_id == command.effect.parent.scope.operator_id)
                .values(
                    access_epoch=command.access_epoch,
                    desired_state=command.payload.desired_state,
                    operation_id=command.effect.child_id(),
                    updated_at=now,
                    revision=table.c.revision + 1,
                )
            )

    def allocation(self, connection, command, *, runtime=False):
        binding = self._binding(connection, command)
        scope = command.effect.parent.scope
        if (
            binding is None
            or binding["operator_id"] != scope.operator_id
            or binding["workspace_id"] != scope.workspace_id
            or binding["resource_generation"] != command.effect.resource_generation
        ):
            raise HostAgentDenied()
        principals = self.table(connection, "operator_principals")
        principal = (
            connection.execute(
                select(principals).where(principals.c.operator_id == scope.operator_id)
            )
            .mappings()
            .one()
        )
        projects = self.table(connection, "project_assignments")
        mapping = dict(
            connection.execute(
                select(projects.c.tree_kind, projects.c.project_id).where(
                    projects.c.binding_id == binding["binding_id"]
                )
            ).all()
        )
        ingress = self.table(connection, "ingress_bindings")
        projection_revision = None
        if command.effect.kind == "apply_ingress_policy":
            ingress = self.table(connection, "ingress_bindings")
            revision = connection.execute(
                select(ingress.c.revision).where(ingress.c.operator_id == scope.operator_id)
            ).scalar_one()
            # Verification is itself a revisioned update. The driver must apply and
            # inspect this sealed next projection before that revision is committed.
            # A crash retains the pending receipt and the same next revision.
            projection_revision = revision + 1
        return Allocation(
            binding_id=binding["binding_id"],
            resource_generation=binding["resource_generation"],
            host_uid=principal["host_uid"],
            host_gid=principal["host_gid"],
            workspace_project=mapping["workspace"],
            control_project=mapping["control"],
            scratch_project=mapping["scratch"],
            filesystem_identity=self.identity.filesystem_identity,
            image_digest=binding["image_digest"],
            container_ref=binding["container_ref"],
            binding_revision=binding["revision"],
            access_epoch=connection.execute(
                select(ingress.c.access_epoch).where(ingress.c.binding_id == binding["binding_id"])
            ).scalar_one(),
            limits=ResourceLimits(
                **{
                    tree: TreeLimits(
                        byte_ceiling=binding[tree + "_byte_ceiling"],
                        inode_ceiling=binding[tree + "_inode_ceiling"],
                    )
                    for tree in ("workspace", "control", "scratch")
                }
            ),
            ingress_projection_revision=projection_revision,
            inputs=None
            if runtime
            else StoredEffect.model_validate_json(
                self.original(connection, command)["request_json"]
            ).inputs,
        )

    def ingress_projection(self):
        """One bounded owning snapshot. No caller origin, path or peer selector."""
        with self.transaction(write=False) as connection:
            table = self.table(connection, "ingress_bindings")
            rows = (
                connection.execute(
                    select(table).order_by(table.c.public_origin).limit(MAX_ORIGINS + 1)
                )
                .mappings()
                .all()
            )
            if len(rows) > MAX_ORIGINS:
                raise HostAgentUnavailable()
            records = []
            for row in rows:
                self._validate_origin(row["public_origin"])
                records.append(
                    IngressRecord(**{key: row[key] for key in IngressRecord.model_fields})
                )
            return IngressProjection(records=tuple(records))

    def network_projection(self):
        """All retained allocations reserve their slot; no address reuse after retirement."""
        with self.transaction(write=False) as connection:
            bindings = self.table(connection, "resource_bindings")
            projects = self.table(connection, "project_assignments")
            rows = (
                connection.execute(
                    select(
                        bindings.c.binding_id,
                        bindings.c.operator_id,
                        bindings.c.workspace_id,
                        bindings.c.resource_generation,
                        projects.c.project_id.label("workspace_project"),
                    )
                    .join(projects, projects.c.binding_id == bindings.c.binding_id)
                    .where(projects.c.tree_kind == "workspace")
                    .order_by(bindings.c.binding_id)
                    .limit(MAX_ORIGINS + 1)
                )
                .mappings()
                .all()
            )
            return NetworkProjection(records=tuple(NetworkRecord(**row) for row in rows))

    def runtime_allocation(self, command):
        """Protected watchdog lookup; inventory identity/scope still owns the target."""
        with self.transaction(write=False) as connection:
            return self.allocation(connection, command, runtime=True)

    def supervision_command(self, historical, container_id):
        """Resolve an immutable stop identity to this binding's current applied start.

        Do not edit the stop projection or synthesize a new command with a fresh
        epoch. Only an actual admitted, applied start may supervise this generation.
        Caller holds the inventory singleton across lookup and physical inspection.
        """
        with self.transaction(write=False) as connection:
            allocation = self.allocation(connection, historical, runtime=True)
            binding = self._binding(connection, historical)
            if (
                binding["state"] != "running"
                or allocation.container_ref is None
                or (container_id is not None and allocation.container_ref != container_id)
            ):
                raise HostAgentDenied()
            ingress = self.table(connection, "ingress_bindings")
            epoch = connection.execute(
                select(ingress.c.access_epoch).where(ingress.c.binding_id == allocation.binding_id)
            ).scalar_one()
            receipts = self.table(connection, "host_receipts")
            request = connection.execute(
                select(receipts.c.request_json).where(
                    receipts.c.binding_id == allocation.binding_id,
                    receipts.c.kind == "start_container",
                    receipts.c.state == "applied",
                    receipts.c.access_epoch == epoch,
                    func.json_extract(receipts.c.request_json, "$.command.expected_revision")
                    == binding["revision"] - 1,
                )
            ).scalar_one_or_none()
            if request is None:
                raise HostAgentDenied()
            current = StoredEffect.model_validate_json(request).command
            if self.allocation(connection, current, runtime=True) != allocation:
                raise HostAgentDenied()
            return current

    def mark_attention(self, command, observed, now):
        with self.transaction() as connection:
            current = self.allocation(connection, command, runtime=True)
            if current != observed:
                raise HostAgentDenied()
            table = self.table(connection, "resource_bindings")
            connection.execute(
                table.update()
                .where(table.c.binding_id == observed.binding_id)
                .values(
                    state="needs_attention", last_verified_at=now, revision=table.c.revision + 1
                )
            )

    def retained(self, command):
        with self.transaction(write=False) as connection:
            row = self.original(connection, command)
            if row is None:
                raise HostAgentDenied()
            if row["state"] in {"applied", "rejected", "superseded"}:
                return safe_receipt(row), None, False
            return (
                safe_receipt(row),
                self.allocation(connection, command),
                self.can_inspect(connection, command),
            )

    def finish(self, command: HostEffect, observation: EffectObservation, now):
        with self.transaction() as connection:
            row = self.original(connection, command)
            if row is None:
                raise HostAgentDenied()
            if row["state"] in {"applied", "rejected", "superseded"}:
                return safe_receipt(row)
            receipt = self.table(connection, "host_receipts")
            connection.execute(
                receipt.update()
                .where(receipt.c.operation_id == row["operation_id"])
                .values(
                    state=observation.status,
                    observed_json=canonical_bytes(observation).decode(),
                    revision=row["revision"] + 1,
                )
            )
            if observation.status == "applied":
                self._apply_observed(connection, command, observation, now)
                if command.effect.kind == "stop_container":
                    self._supersede_contained_starts(connection, command, observation, now)
            return safe_receipt(self.original(connection, command))

    def _supersede_contained_starts(self, connection, stop, observation, now):
        """A verified admitted stop closes start uncertainty, never its original outcome.

        Intent/unknown observation stay retained. Other uncertain effects (creation,
        limits, ingress) are not resolved merely because a container is stopped.
        The stop receipt and these terminal records commit in the same transaction.
        """
        if observation.resource_state != "stopped" or observation.evidence_ref is None:
            raise HostAgentDenied()
        table = self.table(connection, "host_receipts")
        rows = (
            connection.execute(
                select(table).where(
                    table.c.binding_id == stop.effect.binding_id,
                    table.c.kind == "start_container",
                    table.c.state.in_(("pending", "unknown")),
                    table.c.access_epoch <= stop.access_epoch,
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            original = StoredEffect.model_validate_json(row["request_json"]).command
            if (
                original.effect.resource_generation != stop.effect.resource_generation
                or original.effect.parent.scope != stop.effect.parent.scope
                or original.effect.parent.deployment_id != stop.effect.parent.deployment_id
                or original.expected_revision > stop.expected_revision
            ):
                raise HostAgentDenied()
            retained = json.loads(row["observed_json"]) if row["observed_json"] else {}
            retained.update(
                superseded_by_operation_id=stop.effect.child_id(),
                containment_evidence_ref=observation.evidence_ref,
                superseded_at=now,
            )
            connection.execute(
                table.update()
                .where(table.c.operation_id == row["operation_id"])
                .values(
                    state="superseded",
                    observed_json=json.dumps(retained, sort_keys=True),
                    revision=row["revision"] + 1,
                )
            )

    def _apply_observed(self, connection, command, observation, now):
        if command.effect.kind == "apply_ingress_policy":
            table = self.table(connection, "ingress_bindings")
            row = (
                connection.execute(
                    select(table).where(
                        table.c.operator_id == command.effect.parent.scope.operator_id
                    )
                )
                .mappings()
                .one()
            )
            if (
                row["operation_id"] != command.effect.child_id()
                or row["access_epoch"] != command.access_epoch
                or observation.ingress_revision != row["revision"] + 1
            ):
                raise HostAgentDenied()
            connection.execute(
                table.update()
                .where(table.c.operator_id == row["operator_id"])
                .values(
                    verified_state=observation.ingress_state,
                    verified_revision=observation.ingress_revision,
                    verification_ref=observation.evidence_ref,
                    verified_at=now,
                    updated_at=now,
                    revision=row["revision"] + 1,
                )
            )
        elif command.effect.kind == "apply_limits":
            row = self.original(connection, command)
            plan = StoredEffect.model_validate_json(row["request_json"]).inputs.plan
            table = self.table(connection, "resource_bindings")
            values = {"revision": table.c.revision + 1, "last_verified_at": now}
            for tree in ("workspace", "control", "scratch"):
                limits = getattr(plan, tree)
                values.update(
                    {
                        tree + "_byte_ceiling": limits.byte_ceiling,
                        tree + "_inode_ceiling": limits.inode_ceiling,
                    }
                )
            connection.execute(
                table.update()
                .where(table.c.binding_id == command.effect.binding_id)
                .values(**values)
            )
        elif observation.resource_state is not None:
            table = self.table(connection, "resource_bindings")
            values = dict(
                state=observation.resource_state,
                last_verified_at=now,
                revision=table.c.revision + 1,
            )
            if observation.container_ref is not None:
                values["container_ref"] = observation.container_ref
            connection.execute(
                table.update()
                .where(table.c.binding_id == command.effect.binding_id)
                .values(**values)
            )

    def can_inspect(self, connection, command):
        """Old receipts remain readable; obsolete effects cannot be replayed or projected."""
        table = self.table(connection, "ingress_bindings")
        row = (
            connection.execute(
                select(table).where(table.c.operator_id == command.effect.parent.scope.operator_id)
            )
            .mappings()
            .one_or_none()
        )
        if (
            row is None
            or row["binding_id"] != command.effect.binding_id
            or row["access_epoch"] != command.access_epoch
        ):
            return False
        if command.effect.kind == "apply_ingress_policy":
            return row["operation_id"] == command.effect.child_id()
        return self._binding(connection, command)["revision"] == command.expected_revision


def safe_receipt(row):
    observed = json.loads(row["observed_json"]) if row["observed_json"] else {}
    return EffectReceipt(
        operation_id=row["operation_id"],
        parent_operation_id=row["parent_operation_id"],
        idempotency_key=row["idempotency_key"],
        request_hash=row["request_hash"],
        binding_id=row["binding_id"],
        state=row["state"],
        revision=row["revision"],
        evidence_ref=observed.get("evidence_ref"),
        superseded_by_operation_id=observed.get("superseded_by_operation_id"),
        containment_evidence_ref=observed.get("containment_evidence_ref"),
    )


def next_id(bounds: PrincipalRange, used: set[int]) -> int:
    denied = used | set(bounds.reserved)
    candidate = bounds.first
    # Work scales with actual occupied identities, not an attacker-sized numeric range.
    for value in sorted(value for value in denied if bounds.first <= value <= bounds.last):
        if value == candidate:
            candidate += 1
        elif value > candidate:
            break
    if candidate > bounds.last:
        raise HostAgentUnavailable()
    return candidate
