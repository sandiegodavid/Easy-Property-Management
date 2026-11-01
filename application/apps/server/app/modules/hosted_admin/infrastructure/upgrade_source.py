"""Fixed target-UID compatibility probe, shared by private and broker deployment.

Never creates a workspace, installs/migrates a schema, restores data or activates
access. The stopped probe holds the normal server lock for the complete check.
"""

import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path

from app.modules.hosted_access.infrastructure.configuration import load_hosted_deployment
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore
from app.modules.workspace.application.service import WorkspaceService
from app.platform.locking import WorkspaceOperationLock


def check(deployment_path, local_config, *, stopped):
    deployment = load_hosted_deployment(deployment_path)
    workspace = WorkspaceService.from_local_config(local_config)
    lock = (
        WorkspaceOperationLock(
            workspace.paths.root.parent / f".{workspace.paths.root.name}.server.lock"
        )
        if stopped
        else nullcontext()
    )
    with lock:
        state = workspace.open(integrity_check=True)
        if state.workspace_id != str(deployment.workspace_id):
            raise ValueError("Workspace identity differs from this allocation.")
        access = SQLiteHostedSessionStore(deployment, administration=True)
        try:
            maintenance = access.maintenance.current()
            if stopped and maintenance.owner is None:
                raise ValueError("Stopped validation requires an owned maintenance gate.")
            return {
                "workspace_id": state.workspace_id,
                "compatible": True,
                "maintenance_owner": maintenance.owner,
            }
        finally:
            access.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("readiness", "stopped"))
    parser.add_argument("deployment", type=Path)
    parser.add_argument("local", type=Path)
    arguments = parser.parse_args()
    if os.geteuid() == 0:
        raise ValueError("Run the compatibility probe as the isolated service identity.")
    print(
        json.dumps(
            check(arguments.deployment, arguments.local, stopped=arguments.action == "stopped")
        )
    )


if __name__ == "__main__":
    main()
