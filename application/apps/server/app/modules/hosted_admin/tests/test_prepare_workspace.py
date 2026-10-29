"""Exercise the installed seed script and real workspace/API preparation together."""

import json
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

import pytest

from app.modules.hosted_admin.infrastructure import prepare_workspace as helper
from app.modules.workspace.application.service import WorkspaceService
from app.platform.testing_client import LocalApiClient


@pytest.fixture
def installation(tmp_path):
    application = Path(__file__).resolve().parents[6]
    installed = tmp_path / "release/admin-seed"
    installed.mkdir(parents=True)
    for name in ("seed.py", "dataset.json"):
        shutil.copyfile(application / "demo" / name, installed / name)
    root = tmp_path / "volume/workspace"
    root.parent.mkdir()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"localWorkspacePath": str(root)}))
    return config, str(uuid4()), installed / "seed.py"


def retained(service):
    with sqlite3.connect(service.paths.database) as connection:
        return {
            table: connection.execute(f"SELECT id FROM {table} ORDER BY id").fetchall()
            for table in ("parties", "properties", "spaces", "leases")
        }


def test_installed_synthetic_seed_resumes_lost_write_and_completed_retry(installation, monkeypatch):
    config, identifier, seed = installation
    service = WorkspaceService.from_local_config(config)
    original = LocalApiClient.post

    def interrupted(client, *args, **kwargs):
        response = original(client, *args, **kwargs)
        assert response.is_success
        raise RuntimeError("Interrupted after committing the first seed write")

    with monkeypatch.context() as patch:
        patch.setattr(LocalApiClient, "post", interrupted)
        with pytest.raises(RuntimeError, match="Interrupted"):
            helper.prepare(config, identifier, "synthetic", seed)
    assert service.open(integrity_check=True).workspace_id == identifier
    first = retained(service)
    assert len(first["parties"]) == 1
    runtime = service.paths.root.parent / "workspace-demo-runtime"
    metadata = json.loads((runtime / "seed-metadata.json").read_text())
    assert metadata["workspaceId"] == identifier
    journal = json.loads((runtime / "seed-journal.json").read_text())
    assert len(journal) == 1
    assert "result" not in next(iter(journal.values()))

    assert helper.prepare(config, identifier, "synthetic", seed) == identifier
    completed = retained(service)
    assert first["parties"][0] in completed["parties"]
    assert len(completed["properties"]) == len(
        json.loads((seed.parent / "dataset.json").read_text())["properties"]
    )
    catalog = (runtime / "catalog.json").read_bytes()
    journal = (runtime / "seed-journal.json").read_bytes()
    assert helper.prepare(config, identifier, "synthetic", seed) == identifier
    assert retained(service) == completed
    assert (runtime / "catalog.json").read_bytes() == catalog
    assert (runtime / "seed-journal.json").read_bytes() == journal
    assert json.loads((runtime / "seed-metadata.json").read_text()) == metadata


def test_seed_retry_after_initialization_preserves_reservation_and_date(installation, monkeypatch):
    config, identifier, seed = installation
    original = WorkspaceService.initialize

    def interrupted(service, **kwargs):
        original(service, **kwargs)
        raise RuntimeError("Interrupted after initialization")

    with monkeypatch.context() as patch:
        patch.setattr(WorkspaceService, "initialize", interrupted)
        with pytest.raises(RuntimeError, match="Interrupted"):
            helper.prepare(config, identifier, "synthetic", seed)
    # Stop just after the real seed preparation on retry; business writes are
    # covered above, while this asserts the initialization/journal crash window.
    service = WorkspaceService.from_local_config(config)
    runtime = service.paths.root.parent / "workspace-demo-runtime"
    metadata = (runtime / "seed-metadata.json").read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(WorkspaceService, "initialize", interrupted)
        with pytest.raises(RuntimeError, match="Interrupted"):
            helper.prepare(config, identifier, "synthetic", seed)
    assert service.open(integrity_check=True).workspace_id == identifier
    assert (runtime / "seed-metadata.json").read_bytes() == metadata
    assert json.loads((runtime / "seed-journal.json").read_text()) == {}
    with pytest.raises(RuntimeError, match="identity differs"):
        helper.prepare(config, str(uuid4()), "synthetic", seed)


@pytest.mark.parametrize("valid_workspace", [False, True])
def test_synthetic_seed_rejects_populated_unjournaled_destination(installation, valid_workspace):
    config, identifier, seed = installation
    service = WorkspaceService.from_local_config(config)
    if valid_workspace:
        service.initialize(workspace_id=identifier)
    else:
        service.paths.root.mkdir()
        (service.paths.root / "unrelated.txt").write_text("retain these bytes")
    before = sorted(path.relative_to(service.paths.root) for path in service.paths.root.rglob("*"))
    with pytest.raises(RuntimeError, match="populated without a demo journal"):
        helper.prepare(config, identifier, "synthetic", seed)
    assert (
        sorted(path.relative_to(service.paths.root) for path in service.paths.root.rglob("*"))
        == before
    )


def test_empty_template_keeps_reserved_identity_on_retry(installation):
    config, identifier, _ = installation
    assert helper.prepare(config, identifier, "empty") == identifier
    assert helper.prepare(config, identifier, "empty") == identifier
