"""Serve wheel assets with production FastAPI and disposable external workspaces."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import uvicorn

from app.bootstrap.api import create_app
from app.modules.workspace.application.service import WorkspaceService

APPLICATION = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state", choices=("ready", "unavailable"), required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="epm-browser-") as directory:
        root = Path(directory).resolve()
        config = root / "config.json"
        config.write_text(json.dumps({"localWorkspacePath": str(root / "workspace")}))
        if args.state == "ready":
            WorkspaceService.from_local_config(config).initialize()
        wheel = APPLICATION / "dist/easy_property_management-0.1.0-py3-none-any.whl"
        web = root / "web_build"
        with ZipFile(wheel) as archive:
            for name in archive.namelist():
                if name.startswith("app/web_build/"):
                    relative = Path(name).relative_to("app/web_build")
                    if ".." in relative.parts:
                        raise RuntimeError("Unsafe wheel asset")
                    destination = web / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    content = archive.read(name)
                    if content != (APPLICATION / "apps/web/dist" / relative).read_bytes():
                        raise RuntimeError("Wheel assets differ from the current Vite build")
                    destination.write_bytes(content)
        uvicorn.run(
            create_app(config, web_build_path=web),
            host="127.0.0.1",
            port=args.port,
            proxy_headers=False,
        )
        if args.state == "unavailable" and (root / "workspace").exists():
            raise AssertionError("Browser delivery initialized the unavailable workspace")


if __name__ == "__main__":
    main()
