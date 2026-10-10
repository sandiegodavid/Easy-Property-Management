"""Fixture builds exercise production bootstrap without a database or a React scaffold."""

from unittest.mock import patch
import json

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.bootstrap.api import create_app
from app.platform.web_delivery import browser_route

ORIGIN = "http://127.0.0.1:8000"
ID = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def build(tmp_path):
    root = tmp_path / "web_build"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text('<html><script src="/assets/app-1234abcd.js"></script></html>')
    (root / "assets" / "app-1234abcd.js").write_text("console.log('fixture');")
    (root / "assets" / "style.css").write_text("body {color: black}")
    (root / "assets" / "secret.env").write_text("secret")
    (root / "assets" / "app.js.map").write_text("source")
    return root


@pytest.fixture
def client(tmp_path, build):
    config = tmp_path / "local.json"
    config.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "workspace")}))
    app = create_app(config, web_build_path=build)
    with patch.object(Engine, "connect", side_effect=AssertionError("Static delivery opened DB")):
        # No lifespan: request tests must not start the unrelated scheduler.
        yield TestClient(app, base_url=ORIGIN)
    assert not (tmp_path / "workspace").exists()


@pytest.mark.parametrize(
    "path",
    [
        "/home",
        "/properties",
        f"/properties/{ID}/units",
        f"/owners/{ID}/money",
        f"/leases/{ID}/terms",
        f"/tasks/{ID}",
        f"/inspections/{ID}",
        f"/maintenance/issues/{ID}/work-journal",
        f"/money/owner-reports/{ID}/review",
        f"/money/deposit-settlements/{ID}",
        "/money/expenses",
        "/settings/workspace",
        "/search",
    ],
)
def test_registered_deep_links_and_head(client, path):
    response = client.get(path, headers={"Accept": "text/html"})
    assert response.status_code == status.HTTP_200_OK
    assert '<script src="/assets/' in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    head = client.head(path, headers={"Accept": "text/html"})
    assert head.status_code == response.status_code
    assert head.content == b""
    assert head.headers["content-length"] == response.headers["content-length"]


def test_root_redirect_and_static_cache(client):
    assert (
        client.get("/", headers={"Accept": "text/html"}, follow_redirects=False).headers["location"]
        == "/home"
    )
    asset = client.get("/assets/app-1234abcd.js")
    assert asset.status_code == status.HTTP_200_OK
    assert "immutable" in asset.headers["cache-control"]
    assert client.get("/assets/style.css").headers["cache-control"] == "no-cache"
    assert client.head("/assets/style.css").content == b""


@pytest.mark.parametrize(
    "path",
    [
        "/api/not-real",
        "/assets/not-real.js",
        "/assets/secret.env",
        "/assets/app.js.map",
        "/unknown",
        "/intake/review",
        f"/properties/{ID}/not-real",
        "/properties/not-a-uuid",
        "/workspace/manifest.json",
        "/openapi.json/not-real",
    ],
)
def test_unknown_routes_never_fall_back(client, path):
    response = client.get(path, headers={"Accept": "text/html"})
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert '<script src="/assets/' not in response.text


@pytest.mark.parametrize("accept", ["application/json", "*/*", "text/html;q=0", "text/html;q=bad"])
def test_html_accept_required(client, accept):
    assert client.get("/home", headers={"Accept": accept}).status_code == status.HTTP_404_NOT_FOUND


def test_methods_and_transport_policy_remain_truthful(client):
    assert (
        client.post("/home", headers={"Origin": ORIGIN}).status_code
        == status.HTTP_405_METHOD_NOT_ALLOWED
    )
    assert (
        client.post("/assets/style.css", headers={"Origin": ORIGIN}).status_code
        == status.HTTP_405_METHOD_NOT_ALLOWED
    )
    assert (
        client.get("/home", headers={"Origin": "null", "Accept": "text/html"}).status_code
        == status.HTTP_403_FORBIDDEN
    )
    assert (
        client.get("/assets/style.css", headers={"Host": "remote.example"}).status_code
        == status.HTTP_403_FORBIDDEN
    )


@pytest.mark.parametrize(
    "path",
    [
        "/assets/%2e%2e/index.html",
        "/assets/%2fetc/passwd",
        "/assets/..%5cindex.html",
        "/assets/%252e%252e/index.html",
    ],
)
def test_traversal(client, path):
    assert (
        client.get(path, headers={"Accept": "text/html"}).status_code == status.HTTP_404_NOT_FOUND
    )


def test_symlinks_not_served(client, build, tmp_path):
    outside = tmp_path / "outside.js"
    outside.write_text("private")
    (build / "assets" / "outside.js").symlink_to(outside)
    assert client.get("/assets/outside.js").status_code == status.HTTP_404_NOT_FOUND
    (build / "index.html").unlink()
    (build / "index.html").symlink_to(outside)
    response = client.get("/home", headers={"Accept": "text/html"})
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert str(build) not in response.text


def test_missing_build_preserves_api_and_bootstrap(client, build):
    (build / "index.html").unlink()
    assert (
        client.get("/home", headers={"Accept": "text/html"}).json()["detail"]["code"]
        == "web_build_unavailable"
    )
    assert client.get("/openapi.json").status_code == status.HTTP_200_OK
    assert client.get("/docs").status_code == status.HTTP_200_OK
    assert client.get("/redoc").status_code == status.HTTP_200_OK
    assert client.get("/health").status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    response = client.get("/api/operator/bootstrap")
    assert response.status_code == status.HTTP_200_OK


def test_workspace_cannot_be_a_static_root(tmp_path):
    config = tmp_path / "local.json"
    workspace = tmp_path / "workspace"
    config.write_text(json.dumps({"localWorkspacePath": str(workspace)}))
    with pytest.raises(ValueError, match="separate"):
        create_app(config, web_build_path=workspace)
    with pytest.raises(ValueError, match="separate"):
        create_app(config, web_build_path=tmp_path)


def test_allowlist_uses_canonical_ids():
    assert not browser_route("/tasks/" + ID.upper().replace("4000", "ABCD"))
    assert not browser_route("/settings/issue-review")
