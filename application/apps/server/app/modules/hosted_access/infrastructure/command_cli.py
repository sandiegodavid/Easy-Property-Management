"""Fixed per-service-user source runner. JSON only on stdin/stdout, no business workspace."""

import json
from pathlib import Path
import sys

from pydantic import ValidationError

from app.modules.hosted_access.application.admin_commands import AccessCommand, AccessQuery
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.configuration import load_hosted_deployment
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore
from app.modules.hosted_access.infrastructure.source_commands import AccessCommands
from app.modules.hosted_access.infrastructure.configuration import validate_workspace_binding
from app.modules.workspace.application.service import WorkspaceService


def invoke(store, raw, local_config):
    commands = AccessCommands(store)
    if "query" in raw:
        query = AccessQuery.model_validate(raw)
        if query.query == "status":
            return commands.administrative_status().model_dump()
        result = commands.receipt(query.command)
        return {"found": result is not None, "result": result.model_dump() if result else None}
    command = AccessCommand.model_validate(raw)
    original = commands.receipt(command)
    if original:
        return original.model_dump()
    if command.action not in {"disable", "revoke"}:
        # Run validation under the target UID, outside the root broker/HTTP process.
        validate_workspace_binding(
            store.deployment, WorkspaceService.from_local_config(local_config)
        )
    return commands.execute(command).model_dump()


def main():
    store = None
    try:
        if len(sys.argv) != 3:
            raise ValueError()
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError()
        deployment = load_hosted_deployment(Path(sys.argv[1]))
        store = SQLiteHostedSessionStore(deployment)
        print(json.dumps(invoke(store, json.loads(raw), Path(sys.argv[2]))))
    except HostedAccessError as error:
        print(json.dumps({"error": error.code, "status": error.status}))
    except (OSError, ValueError, ValidationError) as _error:
        print(json.dumps({"error": "hosted_admin_source_unavailable", "status": 503}))
    finally:
        if store:
            store.engine.dispose()


if __name__ == "__main__":
    main()
