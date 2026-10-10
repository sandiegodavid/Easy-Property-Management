"""Build a wheel from an isolated source tree containing only public Vite assets."""

from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

APPLICATION = Path(__file__).resolve().parents[1]
PUBLIC_SUFFIXES = {".js", ".css", ".svg", ".png", ".jpg", ".webp", ".ico", ".woff2"}


def public_build_files() -> list[Path]:
    build = APPLICATION / "apps/web/dist"
    files = list(build.rglob("*"))
    if not (build / "index.html").is_file():
        raise RuntimeError("Run npm run build before packaging.")
    for file in files:
        if file.is_symlink():
            raise RuntimeError("Build symlinks cannot be packaged.")
        if file.is_file() and file != build / "index.html":
            if file.parent != build / "assets" or file.suffix not in PUBLIC_SUFFIXES:
                raise RuntimeError(f"Unexpected public build file: {file.name}")
    return [file for file in files if file.is_file()]


def package() -> None:
    files = public_build_files()
    with TemporaryDirectory(prefix="epm-web-package-") as temporary:
        source = Path(temporary)
        shutil.copy(APPLICATION / "pyproject.toml", source / "pyproject.toml")
        package_root = source / "apps/server/app"
        shutil.copytree(
            APPLICATION / "apps/server/app",
            package_root,
            ignore=shutil.ignore_patterns("__pycache__", "tests", "web_build"),
        )
        for file in files:
            destination = (
                package_root / "web_build" / file.relative_to(APPLICATION / "apps/web/dist")
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(file, destination)
        subprocess.run(
            [
                "uv",
                "build",
                str(source),
                "--wheel",
                "--offline",
                "--out-dir",
                str(APPLICATION / "dist"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        print("Packaged public Vite assets into application/dist.")


if __name__ == "__main__":
    package()
