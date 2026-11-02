"""Atomic protected capacity/identity reservations, not a quota-effect worker."""

import json
import sqlite3
from pathlib import PurePosixPath

from app.modules.hosted_access.application.storage_policy import TierProfile
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.storage import (
    HostStorageFacts,
    BindingCheck,
    ProfileEvidence,
    StorageView,
    canonical_storage,
    storage_fingerprint,
)


class StorageAllocations:
    def __init__(self, store, collect, bindings, profile_evidence):
        self.store, self.collect = store, collect
        self.bindings, self.profile_evidence = bindings, profile_evidence

    def register_profile(self, profile):
        """Private installer input; never a browser assertion of qualification."""
        encoded = canonical_storage(profile.model_dump(mode="json"))
        digest = storage_fingerprint(profile.model_dump(mode="json"))
        proof = self.profile_evidence(profile, None) if profile.qualified else None
        if profile.qualified:
            proof = ProfileEvidence.model_validate(proof)
            self.check_evidence(proof, digest)
        with self.store.transaction() as connection:
            prior = connection.execute(
                "SELECT payload FROM storage_profile WHERE id=?", (profile.id,)
            ).fetchone()
            if prior:
                if prior[0] != encoded:
                    raise AdminError("admin_storage_profile_conflict", 409)
                return digest
            connection.execute(
                "INSERT INTO storage_profile VALUES (?,?,?,?,?,?)",
                (
                    profile.id,
                    profile.revision,
                    encoded,
                    digest,
                    canonical_storage(proof.model_dump()) if proof else None,
                    self.store.clock(),
                ),
            )
            self.store._audit(connection, "storage_profile_registered", profile.id)
        return digest

    def reserve(self, command, identity, credential):
        with self.store.transaction() as connection:
            self.authority(connection, identity)
            prior = self.prior(connection, command, identity)
            if prior is not None:
                return prior
            profile_row = connection.execute(
                "SELECT * FROM storage_profile WHERE id=?", (command.policy.profile_id,)
            ).fetchone()
            if profile_row is None or profile_row["digest"] != command.policy.profile_digest:
                raise AdminError("admin_storage_profile_unavailable", 409)
        profile = TierProfile.model_validate_json(profile_row["payload"])
        if not profile.qualified:
            raise AdminError("admin_storage_profile_unavailable", 409)
        proof = ProfileEvidence.model_validate(
            self.profile_evidence(profile, json.loads(profile_row["evidence"]))
        )
        # Slow collection is outside the control transaction; admission rechecks
        # authority and observation freshness under BEGIN IMMEDIATE.
        facts = HostStorageFacts.model_validate(self.collect(command.policy.filesystem_uuid))
        binding = BindingCheck.model_validate(self.bindings(command))
        if binding.authority != command.authority or binding.policy_digest != storage_fingerprint(
            command.policy.model_dump(mode="json")
        ):
            raise AdminError("admin_storage_binding_changed", 409)
        with self.store.transaction() as connection:
            self.authority(connection, identity)
            prior = self.prior(connection, command, identity)
            if prior is not None:
                return prior
            policy = command.policy
            self.store._consume(connection, credential, "action", command.fingerprint())
            if connection.execute("SELECT count(*) FROM storage_allocation").fetchone()[0] >= 1000:
                raise AdminError("admin_storage_capacity_bound", 409)
            if command.expected_revision != 0 or policy.policy_revision != 1:
                raise AdminError("admin_storage_revision_conflict", 409)
            profile_row = connection.execute(
                "SELECT * FROM storage_profile WHERE id=?", (policy.profile_id,)
            ).fetchone()
            if not profile_row or profile_row["digest"] != policy.profile_digest:
                raise AdminError("admin_storage_profile_unavailable", 409)
            profile = TierProfile.model_validate_json(profile_row["payload"])
            if not profile.qualified or profile.tier != policy.tier:
                raise AdminError("admin_storage_profile_unavailable", 409)
            self.check_evidence(proof, policy.profile_digest, facts.environment_hash)
            if (binding.release_digest, binding.sandbox_digest) != (
                profile.release_digest,
                profile.sandbox_digest,
            ):
                raise AdminError("admin_storage_profile_changed", 409)
            for project in policy.projects:
                ceiling = getattr(profile, project.role)
                if (project.hard_bytes, project.hard_inodes) != (
                    ceiling.hard_bytes,
                    ceiling.hard_inodes,
                ):
                    raise AdminError("admin_storage_profile_changed", 409)
            self.room(connection, facts, policy)
            now = self.store.clock()
            try:
                connection.execute(
                    "INSERT INTO storage_allocation VALUES (?,?,?,1,'reserved',?,?,?,?,?,?)",
                    (
                        command.id,
                        policy.instance,
                        policy.filesystem_uuid,
                        canonical_storage(command.model_dump(mode="json")),
                        command.fingerprint(),
                        identity["id"],
                        identity["generation"],
                        now,
                        now,
                    ),
                )
                for project in policy.projects:
                    connection.execute(
                        "INSERT INTO storage_project (filesystem_uuid,project_id,operation_id,role,directory,hard_bytes,hard_inodes) VALUES (?,?,?,?,?,?,?)",
                        (
                            policy.filesystem_uuid,
                            project.project_id,
                            command.id,
                            project.role,
                            project.directory,
                            project.hard_bytes,
                            project.hard_inodes,
                        ),
                    )
                connection.execute(
                    "INSERT INTO storage_event VALUES (?,1,'reserved',?,?,?,?)",
                    (
                        command.id,
                        canonical_storage(command.model_dump(mode="json")),
                        identity["id"],
                        identity["generation"],
                        now,
                    ),
                )
                self.store._audit(connection, "storage_reserved", command.id)
            except sqlite3.IntegrityError as error:
                raise AdminError("admin_storage_identity_conflict", 409) from error
            return self.view(
                connection.execute(
                    "SELECT * FROM storage_allocation WHERE operation_id=?", (command.id,)
                ).fetchone()
            )

    def authority(self, connection, identity):
        current = self.store._identity(connection)
        if (current["id"], current["generation"]) != (identity["id"], identity["generation"]):
            raise AdminError("admin_authority_fenced", 403)

    def prior(self, connection, command, identity):
        row = connection.execute(
            "SELECT * FROM storage_allocation WHERE operation_id=?", (command.id,)
        ).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != command.fingerprint() or (row["identity"], row["generation"]) != (
            identity["id"],
            identity["generation"],
        ):
            raise AdminError("admin_storage_intent_conflict", 409)
        return self.view(dict(row) | {"state": "reserved", "revision": 1})

    def inspect(self, instance, identity):
        from app.modules.hosted_admin.application.storage import StorageInspection

        with self.store.transaction() as connection:
            self.authority(connection, identity)
            row = connection.execute(
                "SELECT * FROM storage_allocation WHERE instance=? ORDER BY created DESC,rowid DESC LIMIT 1",
                (instance,),
            ).fetchone()
            if row is None:
                raise AdminError("admin_storage_not_found", 404)
            values = connection.execute(
                "SELECT count(observed),min(observed),min(enforcement),sum(allocated_bytes),sum(allocated_inodes) FROM storage_project WHERE operation_id=?",
                (row["operation_id"],),
            ).fetchone()
        known = values[0] == 3
        state = (
            "unknown"
            if not known
            else "available"
            if 0 <= self.store.clock() - values[1] < 300
            else "stale"
        )
        return StorageInspection(
            allocation=self.view(row),
            state=state,
            observed=values[1] if known else None,
            enforcement=bool(values[2]) if known else None,
            allocated_bytes=values[3] if known else None,
            allocated_inodes=values[4] if known else None,
        ).model_dump()

    def room(self, connection, facts, policy):
        now = self.store.clock()
        if (
            facts.filesystem_uuid != policy.filesystem_uuid
            or not facts.enforcement
            or not 0 <= now - facts.observed < 300
        ):
            raise AdminError("admin_storage_observation_unavailable", 409)
        rows = connection.execute(
            "SELECT p.*,a.state FROM storage_project p JOIN storage_allocation a ON a.operation_id=p.operation_id WHERE p.filesystem_uuid=? LIMIT 3001",
            (facts.filesystem_uuid,),
        ).fetchall()
        if len(rows) > 3000:
            raise AdminError("admin_storage_capacity_bound", 409)
        requested = [PurePosixPath(p.directory) for p in policy.projects]
        for row in rows:
            old = PurePosixPath(row["directory"])
            if any(path.is_relative_to(old) or old.is_relative_to(path) for path in requested):
                raise AdminError("admin_storage_identity_conflict", 409)
        usage = {item.project_id: item for item in facts.projects}
        if len(usage) != len(facts.projects):
            raise AdminError("admin_storage_observation_unavailable", 409)
        growth_bytes = growth_inodes = 0
        for row in rows:
            if row["state"] == "retired":
                continue
            observed = usage.get(row["project_id"])
            if row["state"] != "reserved" and observed is None:
                raise AdminError("admin_storage_observation_unavailable", 409)
            if observed and (
                not observed.enforcement
                or (observed.hard_bytes, observed.hard_inodes)
                != (row["hard_bytes"], row["hard_inodes"])
            ):
                raise AdminError("admin_storage_observation_unavailable", 409)
            growth_bytes += max(
                0, row["hard_bytes"] - (observed.allocated_bytes if observed else 0)
            )
            growth_inodes += max(
                0, row["hard_inodes"] - (observed.allocated_inodes if observed else 0)
            )
        growth_bytes += sum(p.hard_bytes for p in policy.projects)
        growth_inodes += sum(p.hard_inodes for p in policy.projects)
        reserve = max((facts.total_bytes + 4) // 5, facts.recovery_required, 16 * 1024 * 1024)
        other = facts.shared_overhead + facts.retained_image_growth + facts.administrative_growth
        if (
            facts.free_bytes - growth_bytes - other < reserve
            or facts.free_inodes < growth_inodes + facts.administrative_inodes
        ):
            raise AdminError("admin_storage_capacity_exhausted", 409)

    def check_evidence(self, proof, digest, environment=None):
        if (
            proof.profile_digest != digest
            or not proof.observed <= self.store.clock() < proof.expires
            or (environment is not None and proof.environment_hash != environment)
        ):
            raise AdminError("admin_storage_profile_unavailable", 409)

    @staticmethod
    def view(row):
        policy = json.loads(row["request"])["policy"]
        return StorageView(
            operation_id=row["operation_id"],
            instance=row["instance"],
            revision=row["revision"],
            policy_revision=policy["policy_revision"],
            state=row["state"],
            tier=policy["tier"],
            allowance_bytes=policy["allowance_bytes"],
        ).model_dump()
