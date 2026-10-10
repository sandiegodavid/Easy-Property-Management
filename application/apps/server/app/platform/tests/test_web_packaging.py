"""Build and serve a fixture wheel using the production package-data inventory."""

import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


def test_fixture_wheel_contains_only_public_assets_and_serves_deep_link(tmp_path):
    application = Path(__file__).resolve().parents[5]
    source = tmp_path / "source"
    package = source / "apps" / "server" / "app"
    (package / "platform").mkdir(parents=True)
    shutil.copy(application / "pyproject.toml", source / "pyproject.toml")
    for relative in ("__init__.py", "platform/__init__.py", "platform/web_delivery.py"):
        shutil.copy(application / "apps/server/app" / relative, package / relative)
    web = package / "web_build"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<html>packaged fixture</html>")
    (web / "assets" / "app-1234abcd.js").write_text("console.log('public');")
    for relative in ("workspace.sqlite3", "config.local.json", ".env", "assets/app.js.map"):
        (web / relative).write_text("must not ship")
    wheels = tmp_path / "wheels"
    subprocess.run(
        ["uv", "build", str(source), "--wheel", "--offline", "--out-dir", str(wheels)],
        check=True,
        capture_output=True,
        text=True,
    )
    extracted = tmp_path / "installed"
    with ZipFile(next(wheels.glob("*.whl"))) as wheel:
        assets = {name for name in wheel.namelist() if "/web_build/" in name}
        assert assets == {"app/web_build/index.html", "app/web_build/assets/app-1234abcd.js"}
        wheel.extractall(extracted)
    # Fresh interpreter proves the installed package path, not the repository copy.
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
sys.path.insert(0, sys.argv[1])
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.platform.web_delivery import PACKAGED_WEB_ROOT, PackagedWebMiddleware
app = FastAPI()
app.add_middleware(PackagedWebMiddleware, root=PACKAGED_WEB_ROOT)
client = TestClient(app)
response = client.get('/properties', headers={'Accept': 'text/html'})
assert response.text == '<html>packaged fixture</html>'
assert client.get('/assets/app-1234abcd.js').status_code == 200
assert client.get('/api/not-real', headers={'Accept': 'text/html'}).status_code == 404
""",
            str(extracted),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
