"""Commands for the local application."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.modules.workspace.application.service import WorkspaceService


def _config_path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Easy Property Management")
    parser.add_argument(
        "--config",
        help="Path to the ignored local workspace configuration file.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("initialize-workspace", help="Create the configured workspace.")
    commands.add_parser("workspace-status", help="Validate and display the configured workspace.")
    serve_parser = commands.add_parser("serve", help="Run the local FastAPI server.")
    serve_parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    config_path = _config_path(args.config)
    service = WorkspaceService.from_local_config(config_path)

    if args.command == "initialize-workspace":
        manifest = service.initialize()
        print(f"Workspace ready: {service.paths.root}")
        print(f"Workspace ID: {manifest.workspace_id}")
        return

    if args.command == "workspace-status":
        manifest = service.open()
        print(f"Workspace ready: {service.paths.root}")
        print(f"Workspace ID: {manifest.workspace_id}")
        print(f"Format version: {manifest.format_version}")
        return

    from app.bootstrap.api import create_app
    import uvicorn

    uvicorn.run(create_app(config_path), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
