"""Root-peer-only commands for durable work and bounded capacity qualification."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.qualification import (
    QualificationCommand,
    QualificationPlan,
    UUID_PATTERN,
)
from app.modules.hosted_admin.infrastructure.authority import SourceEffect
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
    ]
    plan: QualificationPlan | None = None
    command: QualificationCommand | None = None
    identifier: str | None = Field(default=None, pattern=UUID_PATTERN)
    credential: str = Field(default="", max_length=128)
    ceiling: int | None = Field(default=None, ge=0, le=2)
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def coherent(self):
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
        }
        if uses_identifier != (self.identifier is not None):
            raise ValueError("Only identified operations accept a selector.")
        if (self.action == "capacity-initialize") != (self.ceiling is not None):
            raise ValueError("Only initial installation accepts a ceiling.")
        if (self.action == "operation-stop") != (self.expected_revision is not None):
            raise ValueError("Stopping an operation requires its reviewed revision.")
        if self.credential and self.action != "qualification-command":
            raise ValueError("Only the exact qualification command consumes a credential.")
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
        }
        return handlers[request.action]()

    def initialize(self, ceiling):
        snapshot = self.qualification.snapshot()
        self.qualification._fresh(snapshot)
        self.qualification.initialize_capacity(ceiling, snapshot)
        return {"initialized": True, "ceiling": ceiling}

    def run(self, identifier):
        operation = self.engine.get(identifier)
        if operation["kind"] != "source" and self.provisioning is None:
            raise AdminError("admin_effect_adapter_not_installed", 409)
        self.engine.run(
            identifier,
            SourceEffect(self.dispatch) if operation["kind"] == "source" else self.provisioning,
        )
        return self.engine.get(identifier)

    def stop(self, identifier, expected_revision, identity):
        operation = self.engine.get(identifier)
        if operation["kind"] != "source" and self.provisioning is None:
            raise AdminError("admin_effect_adapter_not_installed", 409)
        self.engine.cancel(identifier, expected_revision, identity)
        self.engine.finish_cancel(
            identifier,
            SourceEffect(self.dispatch) if operation["kind"] == "source" else self.provisioning,
        )
        return self.engine.get(identifier)

    def resume_grant(self, identifier):
        with self.authority.transaction() as connection:
            operation = self.engine._get(connection, identifier)
        return {"credential": self.authority.issue(self.engine.resume_hash(operation))}
