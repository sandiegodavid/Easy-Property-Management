"""Stage validated public frontend assets for the checkout-based server."""

import argparse
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from package_web import APPLICATION, public_build_files


def stage() -> Path:
    source = APPLICATION / "apps/web/dist"
    target = APPLICATION / "apps/server/app/web_build"
    if source.is_symlink():
        raise RuntimeError("Refusing a symlinked frontend build directory.")
    files = public_build_files()
    if target.is_symlink() or target.parent.resolve() != target.parent:
        raise RuntimeError("Refusing a symlinked destination or package directory.")
    if target.exists() and not target.is_dir():
        raise RuntimeError("The generated frontend destination is not a directory.")

    # Prepare the complete replacement before changing the existing build.
    with TemporaryDirectory(prefix=".web-build-stage-", dir=target.parent) as temporary:
        staging = Path(temporary) / "next"
        staging.mkdir()
        for file in files:
            destination = staging / file.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, destination)
        previous = Path(temporary) / "previous"
        if target.exists():
            target.rename(previous)
        try:
            staging.rename(target)
        except OSError:
            if previous.exists():
                previous.rename(target)
            raise
    return target


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage frontend assets for the checkout runtime. Stop the server first."
    )
    parser.parse_args()
    try:
        target = stage()
    except (OSError, RuntimeError) as error:
        parser.exit(1, f"Frontend staging failed: {error}\n")
    print(f"Frontend staged: {target}")
    print("Start the server with the intended workspace configuration.")


if __name__ == "__main__":
    main()
