"""Fixed unprivileged fresh-workspace initializer/validator, invoked through runuser."""

import argparse
from datetime import date
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

from app.modules.workspace.application.service import WorkspaceService


def prepare(config, identifier, template, seed_path=None):
    if os.geteuid() == 0:
        raise ValueError("Workspace preparation must run as its service identity.")
    service = WorkspaceService.from_local_config(config)
    if template == "synthetic":
        from app.platform.testing_client import LocalApiClient
        from app.bootstrap.api import create_app

        # The root adapter qualifies this exact installed script and dataset
        # digest before dropping privileges. No edited workspace is cloned.
        spec = importlib.util.spec_from_file_location("epm_installed_seed", seed_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _, seed_config, journal, runtime, as_of = module.prepare(
            SimpleNamespace(workspace=service.paths.root, as_of=date.today()),
            workspace_id=identifier,
        )
        plan = json.loads((seed_path.parent / "dataset.json").read_text())
        with LocalApiClient(create_app(seed_config)) as client:
            seed = module.Seeder(client, journal, as_of)
            seed.owners(plan)
            seed.providers(plan)
            for item in plan["properties"]:
                seed.property(item)
            seed.expenses()
            for item in plan["issues"]:
                seed.issue(item)
            seed.communications(plan)
            seed.inspection()
            seed.rent_follow_up()
            module.save_json(runtime / "catalog.json", {"asOf": as_of.isoformat(), **seed.catalog})
    else:
        service.initialize(workspace_id=identifier)
    return service.open(integrity_check=True).workspace_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("config", type=Path)
    parser.add_argument("identifier")
    parser.add_argument("template", choices=("synthetic", "empty"))
    parser.add_argument("--seed", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        identifier = prepare(args.config, args.identifier, args.template, args.seed)
    else:
        identifier = (
            WorkspaceService.from_local_config(args.config).open(integrity_check=True).workspace_id
        )
    if identifier != args.identifier:
        raise ValueError("Workspace identity differs from its reservation.")
    print(json.dumps({"workspace_id": identifier, "verified": True}))


if __name__ == "__main__":
    main()
