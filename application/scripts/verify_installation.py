"""Verify installed wheel assets and schema discovery without opening a workspace."""

import argparse
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
import sys


def verify(*, component: str | None = None) -> None:
    if component is not None:
        sys.dont_write_bytecode = True
        runtime = import_module("app.hosted_candidates.runtime")
        print(runtime.inspect(component))
        print("Unqualified candidate inventory verified; hosted runtime remains unavailable.")
        return
    package = import_module("app")
    root = Path(package.__file__).resolve().parent
    if not (root / "web_build/index.html").is_file():
        raise RuntimeError(
            "Wheel is missing its compiled frontend; obtain a combined release wheel."
        )
    if not any((root / "web_build/assets").glob("*.js")):
        raise RuntimeError("Compiled JavaScript assets are missing.")
    revision = import_module("app.platform.product_migrations").current_revision()
    if revision is None:
        raise RuntimeError("No current schema revision was found in the staged resources.")
    print("Application version:", version("easy-property-management"))
    print("Installed Python package:", root)
    print("Current schema revision:", revision)
    print("Installed resource checks passed; workspace/browser acceptance is still required.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=("admin", "operator", "host_agent"))
    args = parser.parse_args()
    try:
        verify(component=args.component)
    except Exception as error:
        parser.exit(1, f"Installation verification failed: {error}\n")


if __name__ == "__main__":
    main()
