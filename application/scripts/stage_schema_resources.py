"""Stage matching schema resources beside a wheel installed in a virtual environment."""

import argparse
from importlib import import_module
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory


def stage(source: Path) -> Path:
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("Activate the dedicated application virtual environment first.")
    target = import_module("app.platform.config").application_root().resolve()
    runtime = Path(sys.prefix).resolve()
    if not target.is_relative_to(runtime):
        raise RuntimeError("Installed application must be inside the active virtual environment.")
    source = source.expanduser().resolve()
    migrations = source / "database/sqlite-migrations"
    if not (source / "alembic.ini").is_file():
        raise RuntimeError("The matching alembic.ini is missing from the release bundle.")
    if not (migrations / "env.py").is_file() or not any((migrations / "versions").glob("*.py")):
        raise RuntimeError("The complete matching schema-resource folder is required.")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise RuntimeError("Schema resources must not contain symlinks.")
    if any(
        path.exists() or path.is_symlink() for path in (target / "alembic.ini", target / "database")
    ):
        raise RuntimeError("Schema resources already exist; use a fresh release environment.")

    with TemporaryDirectory(prefix=".epm-schema-", dir=target) as temporary:
        prepared = Path(temporary)
        shutil.copytree(migrations, prepared / "database/sqlite-migrations")
        shutil.copy2(source / "alembic.ini", prepared / "alembic.ini")
        (prepared / "database").rename(target / "database")
        try:
            (prepared / "alembic.ini").rename(target / "alembic.ini")
        except OSError:
            (target / "database").rename(prepared / "database")
            raise
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Matching release's schema-resources folder.")
    args = parser.parse_args()
    try:
        target = stage(args.source)
    except (OSError, RuntimeError, ImportError) as error:
        parser.exit(1, f"Schema staging failed: {error}\n")
    print(f"Schema resources staged: {target}")


if __name__ == "__main__":
    main()
