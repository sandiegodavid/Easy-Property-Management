"""Export the composed contract without touching a workspace or opening SQLite."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy.engine import Engine

from app.bootstrap.api import create_app


def export() -> str:
    with TemporaryDirectory(prefix="epm-openapi-") as directory:
        root = Path(directory)
        workspace = root / "never-created"
        config = root / "config.json"
        config.write_text(json.dumps({"localWorkspacePath": str(workspace)}))
        with patch.object(Engine, "connect", side_effect=AssertionError("OpenAPI opened SQLite")):
            schema = create_app(config).openapi()
        if workspace.exists():
            raise AssertionError("OpenAPI initialized a workspace")
        operations = [
            operation["operationId"]
            for path in schema["paths"].values()
            for method, operation in path.items()
            if method in {"get", "post", "put", "patch", "delete", "head", "options"}
        ]
        if len(operations) != len(set(operations)):
            raise AssertionError("OpenAPI operation IDs must be unique")
        return json.dumps(schema, sort_keys=True, indent=2) + "\n"


if __name__ == "__main__":
    print(export(), end="")
