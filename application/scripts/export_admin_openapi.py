"""Deterministic private setup schemas, without a workspace or installed host."""

import json

from app.modules.hosted_admin.application.setup import (
    SetupCommand,
    SetupDirectory,
    SetupOptions,
    SetupView,
)
from app.modules.hosted_admin.application.contracts import CommandRequest
from app.modules.hosted_admin.application.recovery import RecoveryCheck, RecoveryReport
from app.modules.hosted_access.application.admin_commands import AccessStatus


def specification():
    schemas = {}
    for model in (
        SetupCommand,
        SetupDirectory,
        SetupOptions,
        SetupView,
        CommandRequest,
        RecoveryCheck,
        RecoveryReport,
        AccessStatus,
    ):
        value = model.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(value.pop("$defs", {}))
        schemas[model.__name__] = value
    return {
        "openapi": "3.1.0",
        "info": {"title": "Private Admin setup", "version": "1"},
        "paths": {},
        "components": {"schemas": schemas},
    }


if __name__ == "__main__":
    print(json.dumps(specification(), indent=2) + "\n", end="")
