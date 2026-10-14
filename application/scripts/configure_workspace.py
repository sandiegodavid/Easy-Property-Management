"""Create a private workspace locator without overwriting config or initializing data."""

import argparse
import json
import os
from pathlib import Path


def absolute_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("An absolute path is required.")
    return path.resolve()


def configure(config: Path, workspace: Path) -> None:
    config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(
            {"localWorkspacePath": str(workspace), "fileStorageProvider": "local"},
            stream,
            indent=2,
        )
        stream.write("\n")
    print(f"Configuration created: {config}")
    print(f"Workspace selected: {workspace}")
    print(
        "No workspace was initialized. Run workspace-status, initialize-workspace or restore next."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=absolute_path, help="New locator file.")
    parser.add_argument(
        "--workspace", required=True, type=absolute_path, help="External data folder."
    )
    args = parser.parse_args()
    try:
        configure(args.config, args.workspace)
    except OSError as error:
        parser.exit(1, f"Configuration creation failed: {error}\n")


if __name__ == "__main__":
    main()
