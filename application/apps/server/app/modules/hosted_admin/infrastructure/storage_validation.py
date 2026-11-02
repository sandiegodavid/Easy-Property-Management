"""Exact portable protected storage history; no restored evidence grants execution."""

from pathlib import PurePosixPath

from app.modules.hosted_access.application.storage_policy import TierProfile
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.storage import (
    ProfileEvidence,
    StorageCommand,
    StorageProof,
    StorageReservation,
    StorageView,
    canonical_storage,
    storage_fingerprint,
    verify_storage_proof,
)


def require(value):
    if not value:
        raise AdminError("admin_storage_data_invalid", 503)


def audited(connection, action, reference):
    require(
        connection.execute(
            "SELECT 1 FROM audit WHERE action=? AND reference=?", (action, reference)
        ).fetchone()
    )


def validate_storage(connection):
    try:
        validate_records(connection)
    except (ValueError, KeyError, TypeError) as error:
        raise AdminError("admin_storage_data_invalid", 503) from error


def validate_records(connection):
    profiles = {}
    for row in connection.execute("SELECT * FROM storage_profile"):
        profile = TierProfile.model_validate_json(row["payload"])
        require(canonical_storage(profile.model_dump(mode="json")) == row["payload"])
        require(storage_fingerprint(profile.model_dump(mode="json")) == row["digest"])
        require(
            (profile.id, profile.revision) == (row["id"], row["revision"]) and row["created"] >= 0
        )
        if profile.qualified:
            proof = ProfileEvidence.model_validate_json(row["evidence"])
            require(
                canonical_storage(proof.model_dump()) == row["evidence"]
                and proof.profile_digest == row["digest"]
            )
            require(proof.observed <= row["created"] < proof.expires)
        else:
            require(row["evidence"] is None)
        audited(connection, "storage_profile_registered", row["id"])
        profiles[profile.id] = profile, row["digest"]
    paths = {}
    seen_commands = set()
    for row in connection.execute("SELECT * FROM storage_allocation"):
        request = StorageReservation.model_validate_json(row["request"])
        policy = request.policy
        pair = profiles.get(policy.profile_id)
        require(
            request.id == row["operation_id"]
            and request.expected_revision == 0
            and policy.policy_revision == 1
        )
        require(
            request.fingerprint() == row["fingerprint"]
            and canonical_storage(request.model_dump(mode="json")) == row["request"]
        )
        require(
            (policy.instance, policy.filesystem_uuid) == (row["instance"], row["filesystem_uuid"])
        )
        require(
            pair
            and pair[0].qualified
            and pair[1] == policy.profile_digest
            and pair[0].tier == policy.tier
        )
        require(
            row["generation"] >= 1
            and row["identity"].strip()
            and 0 <= row["created"] <= row["updated"]
        )
        projects = connection.execute(
            "SELECT * FROM storage_project WHERE operation_id=?", (request.id,)
        ).fetchall()
        require(len(projects) == 3)
        expected = {p.role: p for p in policy.projects}
        for project in projects:
            retained = expected[project["role"]]
            ceiling = getattr(pair[0], retained.role)
            require(
                (
                    project["filesystem_uuid"],
                    project["project_id"],
                    project["directory"],
                    project["hard_bytes"],
                    project["hard_inodes"],
                )
                == (
                    policy.filesystem_uuid,
                    retained.project_id,
                    retained.directory,
                    retained.hard_bytes,
                    retained.hard_inodes,
                )
            )
            require(
                (retained.hard_bytes, retained.hard_inodes)
                == (ceiling.hard_bytes, ceiling.hard_inodes)
            )
            path = PurePosixPath(retained.directory)
            prior = paths.setdefault(policy.filesystem_uuid, [])
            require(not any(path.is_relative_to(p) or p.is_relative_to(path) for p in prior))
            prior.append(path)
        events = connection.execute(
            "SELECT * FROM storage_event WHERE operation_id=? ORDER BY revision", (request.id,)
        ).fetchall()
        require(
            len(events) == row["revision"]
            and events[0]["action"] == "reserved"
            and events[0]["revision"] == 1
        )
        require(
            events[0]["payload"] == row["request"]
            and events[0]["identity"] == row["identity"]
            and events[0]["generation"] == row["generation"]
            and events[0]["created"] == row["created"]
        )
        audited(connection, "storage_reserved", request.id)
        state = "reserved"
        last_proof = None
        for revision, event in enumerate(events[1:], 2):
            command = StorageCommand.model_validate_json(event["payload"])
            require(
                event["revision"] == revision
                and command.expected_revision == revision - 1
                and command.operation_id == request.id
                and command.action == event["action"]
            )
            require(
                event["created"] >= events[revision - 2]["created"]
                and event["generation"] >= events[revision - 2]["generation"]
            )
            receipt = connection.execute(
                "SELECT * FROM storage_command WHERE id=?", (command.id,)
            ).fetchone()
            require(receipt is not None and receipt["request"] == event["payload"])
            require(
                (receipt["identity"], receipt["generation"], receipt["created"])
                == (event["identity"], event["generation"], event["created"])
            )
            allowed = {
                "apply": {"reserved"},
                "reconcile": {"reserved", "active"},
                "retire": {"reserved", "active"},
                "finish_retirement": {"retiring"},
            }
            require(state in allowed[command.action])
            state = {
                "apply": "active",
                "reconcile": "active",
                "retire": "retiring",
                "finish_retirement": "retired",
            }[command.action]
            view = StorageView.model_validate_json(receipt["result"])
            require(canonical_storage(view.model_dump()) == receipt["result"])
            require(
                view.model_dump()
                == dict(
                    operation_id=request.id,
                    instance=policy.instance,
                    revision=revision,
                    policy_revision=1,
                    state=state,
                    tier=policy.tier,
                    allowance_bytes=policy.allowance_bytes,
                )
            )
            if command.action == "retire":
                require(receipt["proof"] == "{}")
            else:
                last_proof = StorageProof.model_validate_json(receipt["proof"])
                require(canonical_storage(last_proof.model_dump()) == receipt["proof"])
                verify_storage_proof(
                    command, policy.model_dump(mode="json"), last_proof, receipt["created"]
                )
            seen_commands.add(command.id)
            audited(connection, "storage_" + command.action, command.id)
        require(state == row["state"] and row["updated"] == events[-1]["created"])
        usage = {p.project_id: p for p in last_proof.projects} if last_proof else {}
        for project in projects:
            last = usage.get(project["project_id"])
            actual = (
                project["allocated_bytes"],
                project["allocated_inodes"],
                project["observed"],
                project["enforcement"],
            )
            expected_usage = (
                (
                    last.allocated_bytes,
                    last.allocated_inodes,
                    last_proof.observed,
                    int(last.enforcement),
                )
                if last
                else (0, 0, None, 0)
            )
            require(actual == expected_usage)
    require(
        seen_commands == {row[0] for row in connection.execute("SELECT id FROM storage_command")}
    )
    for attempt in connection.execute("SELECT * FROM storage_attempt"):
        command = StorageCommand.model_validate_json(attempt["request"])
        require(command.id == attempt["id"] and command.operation_id == attempt["operation_id"])
        require(
            canonical_storage(command.model_dump()) == attempt["request"]
            and attempt["created"] >= 0
            and attempt["generation"] >= 1
        )
        row = connection.execute(
            "SELECT revision FROM storage_allocation WHERE operation_id=?", (command.operation_id,)
        ).fetchone()
        require(row and command.expected_revision <= row[0])
        receipt = connection.execute(
            "SELECT * FROM storage_command WHERE id=?", (command.id,)
        ).fetchone()
        if receipt:
            require(
                (attempt["identity"], attempt["generation"], attempt["request"])
                == (receipt["identity"], receipt["generation"], receipt["request"])
                and attempt["created"] <= receipt["created"]
            )
        audited(connection, "storage_action_admitted", command.id)
    require(
        seen_commands <= {row[0] for row in connection.execute("SELECT id FROM storage_attempt")}
    )
