"""Root-peer-only commands for durable work and bounded capacity qualification."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.hosted_admin.application.contracts import AdminError, CommandRequest
from app.modules.hosted_admin.application.qualification import (
    QualificationCommand,
    QualificationPlan,
    UUID_PATTERN,
)
from app.modules.hosted_admin.infrastructure.authority import SourceEffect
from app.modules.hosted_admin.application.upgrades import UpgradeCommand
from app.modules.hosted_admin.application.upgrade_batches import BatchCommand
from app.modules.hosted_admin.infrastructure.upgrades import UpgradeEffects
from app.modules.hosted_admin.infrastructure.operations import OperationEngine


class PrivateOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal[
        "qualification-create",
        "qualification-command",
        "qualification-evidence",
        "qualification-status",
        "qualification-grant",
        "capacity-initialize",
        "operation-run",
        "operation-stop",
        "operation-status",
        "resume-grant",
        "recovery-register",
        "access-admit",
        "upgrade-grant",
        "upgrade-admit",
        "batch-grant",
        "batch-admit",
        "batch-status",
        "batch-list",
        "batch-run",
    ]
    plan: QualificationPlan | None = None
    command: QualificationCommand | None = None
    identifier: str | None = Field(default=None, pattern=UUID_PATTERN)
    credential: str = Field(default="", max_length=128)
    ceiling: int | None = Field(default=None, ge=0, le=2)
    expected_revision: int | None = Field(default=None, ge=1)
    report_id: str | None = Field(default=None, pattern=UUID_PATTERN)
    source_command: CommandRequest | None = None
    upgrade: UpgradeCommand | None = None
    batch: BatchCommand | None = None
    page: int = Field(default=0, ge=0, le=990, multiple_of=10)

    @model_validator(mode="after")
    def coherent(self):
        if self.action != "batch-list" and self.page:
            raise ValueError("Only batch history accepts pagination.")
        if (self.action in {"batch-grant", "batch-admit"}) != (self.batch is not None):
            raise ValueError("Select the exact batch intent.")
        if (self.action in {"upgrade-grant", "upgrade-admit"}) != (self.upgrade is not None):
            raise ValueError("Select the exact upgrade command.")
        if (self.action == "qualification-create") != (self.plan is not None):
            raise ValueError("Only qualification creation accepts a plan.")
        if (self.action in {"qualification-command", "qualification-grant"}) != (
            self.command is not None
        ):
            raise ValueError("The exact qualification command is required.")
        uses_identifier = self.action in {
            "qualification-evidence",
            "qualification-status",
            "operation-run",
            "operation-stop",
            "operation-status",
            "resume-grant",
            "recovery-register",
            "batch-status",
            "batch-run",
        }
        if uses_identifier != (self.identifier is not None):
            raise ValueError("Only identified operations accept a selector.")
        if (self.action == "capacity-initialize") != (self.ceiling is not None):
            raise ValueError("Only initial installation accepts a ceiling.")
        if (self.action == "operation-stop") != (self.expected_revision is not None):
            raise ValueError("Stopping an operation requires its reviewed revision.")
        if self.credential and self.action not in {
            "qualification-command",
            "access-admit",
            "upgrade-admit",
            "batch-admit",
        }:
            raise ValueError("Only the exact qualification command consumes a credential.")
        if (self.action == "recovery-register") != (self.report_id is not None):
            raise ValueError("Recovery registration requires a protected report identity.")
        if (self.action == "access-admit") != (self.source_command is not None):
            raise ValueError("Access admission requires its exact source command.")
        return self


class PrivateOperations:
    def __init__(self, authority, qualification, dispatch, provisioning=None):
        self.provisioning = provisioning
        self.authority, self.qualification, self.dispatch = authority, qualification, dispatch
        self.engine = OperationEngine(authority)

    def handle(self, payload):
        request = PrivateOperationRequest.model_validate(payload)
        with self.authority.transaction() as connection:
            identity = dict(self.authority._identity(connection))
        handlers = {
            "qualification-create": lambda: self.qualification.create(request.plan, identity),
            "qualification-command": lambda: self.qualification.command(
                request.command, identity, request.credential
            ),
            "qualification-evidence": lambda: self.qualification.register(
                request.identifier, identity
            ),
            "qualification-status": lambda: self.qualification.status(request.identifier),
            "qualification-grant": lambda: {
                "credential": self.authority.issue(request.command.fingerprint())
            },
            "capacity-initialize": lambda: self.initialize(request.ceiling),
            "operation-run": lambda: self.run(request.identifier),
            "operation-stop": lambda: self.stop(
                request.identifier, request.expected_revision, identity
            ),
            "operation-status": lambda: self.engine.get(request.identifier, identity["id"]),
            "resume-grant": lambda: self.resume_grant(request.identifier),
            "recovery-register": lambda: self.dispatch.recovery.register(
                request.identifier, request.report_id
            ),
            "access-admit": lambda: self.admit(request),
            "upgrade-grant": lambda: {
                "credential": self.authority.issue(request.upgrade.fingerprint())
            },
            "upgrade-admit": lambda: self.dispatch.upgrades.command(
                request.upgrade, identity, request.credential
            ),
            "batch-grant": lambda: {
                "credential": self.authority.issue(request.batch.fingerprint())
            },
            "batch-admit": lambda: self.dispatch.upgrades.batches.command(
                request.batch, identity, request.credential
            ),
            "batch-status": lambda: self.dispatch.upgrades.batches.view(
                request.identifier, identity, limit=50
            ),
            "batch-list": lambda: self.dispatch.upgrades.batches.directory(identity, request.page),
            "batch-run": lambda: self.batch_run(request.identifier, identity),
        }
        return handlers[request.action]()

    def batch_run(self, identifier, identity):
        batches = self.dispatch.upgrades.batches
        view = batches.view(identifier, identity)
        batches.tick(view["id"])
        return batches.view(view["id"], identity)

    def admit(self, request):
        def prepare(_key):
            return self.dispatch.prepare_command(request.source_command)

        admitted = self.authority.private_admit(request.source_command, request.credential, prepare)
        return self.engine.get(admitted["id"])

    def initialize(self, ceiling):
        snapshot = self.qualification.snapshot()
        self.qualification._fresh(snapshot)
        self.qualification.initialize_capacity(ceiling, snapshot)
        return {"initialized": True, "ceiling": ceiling}

    def adapter(self, operation):
        if operation["kind"].startswith("upgrade"):
            upgrades = getattr(self.dispatch, "upgrades", None)
            if upgrades is None:
                raise AdminError("admin_upgrade_unavailable", 503)
            return UpgradeEffects(upgrades)
        return SourceEffect(self.dispatch) if operation["kind"] == "source" else self.provisioning

    def run(self, identifier):
        operation = self.engine.get(identifier)
        if operation["kind"] != "source" and self.provisioning is None:
            raise AdminError("admin_effect_adapter_not_installed", 409)
        self.engine.run(
            identifier,
            self.adapter(operation),
        )
        return self.engine.get(identifier)

    def stop(self, identifier, expected_revision, identity):
        operation = self.engine.get(identifier)
        if operation["kind"] != "source" and self.provisioning is None:
            raise AdminError("admin_effect_adapter_not_installed", 409)
        self.engine.cancel(identifier, expected_revision, identity)
        self.engine.finish_cancel(
            identifier,
            self.adapter(operation),
        )
        return self.engine.get(identifier)

    def resume_grant(self, identifier):
        with self.authority.transaction() as connection:
            operation = self.engine._get(connection, identifier)
        return {"credential": self.authority.issue(self.engine.resume_hash(operation))}
