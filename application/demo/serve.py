"""Serve the synthetic workspace with the application's compiled browser UI."""

import argparse
from pathlib import Path

import uvicorn

from app.bootstrap.api import create_app


def main():
    demo = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=demo / "config.local.json")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    web = demo.parent / "apps/web/dist"
    if not args.config.is_file():
        parser.error("Generate the demo first; see demo/README.md.")
    if not (web / "index.html").is_file():
        parser.error("Build the browser UI first: npm run build (from application/).")
    uvicorn.run(create_app(args.config, web_build_path=web), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
