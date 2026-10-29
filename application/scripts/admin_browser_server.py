"""Disposable private-Admin browser fixture. Never install this helper on a host."""

import argparse
from contextlib import contextmanager
from pathlib import Path
import tempfile
import time
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import Request
import uvicorn

from app.modules.hosted_admin.api.application import create_admin_app
from app.modules.hosted_admin.application.contracts import AdminError, BrokerRequest
from app.modules.hosted_admin.infrastructure.authority import AuthorityStore
from app.modules.hosted_admin.infrastructure.console import ConsoleReads
from app.modules.hosted_admin.infrastructure.operations import OperationEngine
from app.modules.hosted_admin.infrastructure.authority import SourceEffect
from app.modules.hosted_admin.application.contracts import CommandRequest
from app.modules.hosted_admin.application.console import (
    RegisteredOperator,
    AccessObservation,
    RuntimeObservation,
    TunnelObservation,
    DiscrepancyObservation,
)
from app.modules.hosted_admin.application.qualification import CapacitySnapshot
from app.modules.hosted_admin.application.operations import Observation, Reservation
from app.modules.hosted_admin.infrastructure.setup import SetupService, SetupWorker


class FixtureSetup:
    """Synthetic effect port only; never creates Unix users, mounts or ingress."""

    def __init__(self):
        self.allowed = False
        self.provider_ready = False
        self.effects = {}
        self.calls = []
        self.approved = False
        self.pending = False

    def options(self):
        return {
            "releases": ["release-20261028-01"],
            "templates": ["synthetic", "empty"],
            "workspace_mib": 250,
            "file_mib": 50,
            "backup_policy": "Synthetic recovery verification is required before access.",
        }

    def plan(self, identifier, data):
        key = "d-" + identifier[:8]
        ids = {
            label + "_id": str(uuid5(NAMESPACE_URL, identifier + ":" + label))
            for label in ("instance", "allocation", "operator", "workspace")
        }
        port = 8000 + int(identifier[:8], 16) % 1000
        values = {
            "email": data.email,
            "hostname": key + ".example.test",
            "port": str(port),
            "user": "epm-" + key,
            "workspace": ids["workspace_id"],
            "mount": "/synthetic/" + key + "/volume",
            "image": "/synthetic/" + key + ".ext4",
            "disk": key,
            "memory": key,
        }
        return {
            "key": key,
            **ids,
            "hostname": values["hostname"],
            "port": port,
            "profile": "synthetic-test",
            "config_hash": "a" * 64,
            "reservations": [
                Reservation(
                    kind=kind, identity=value, amount=1 if kind in {"disk", "memory"} else 0
                ).model_dump()
                for kind, value in sorted(values.items())
            ],
        }

    @contextmanager
    def admission(self, identifier, data):
        yield {"plan": self.plan(identifier, data)}

    def check(self, connection, plan, _prepared):
        if not self.allowed:
            raise AdminError("admin_capacity_unqualified", 409)
        email = next(item["identity"] for item in plan["reservations"] if item["kind"] == "email")
        if connection.execute(
            "SELECT 1 FROM reservation WHERE kind='email' AND lower(identity)=lower(?)", (email,)
        ).fetchone():
            raise AdminError("admin_operator_email_exists", 409)

    def inspect(self, payload, step):
        if step == "provider_setup" and not self.provider_ready:
            return Observation("waiting")
        return self.effects.get((payload["operation_id"], step), Observation("absent"))

    def apply(self, payload, step):
        self.calls.append((payload["target"], step))
        self.effects[payload["operation_id"], step] = Observation(
            "verified", {"verified": True}, payload["target"]
        )

    def contain(self, payload):
        self.calls.append((payload["target"], "contain"))
        return True

    def enrollment(self, _key):
        return {
            "approved": self.approved,
            "issuer": "https://synthetic.cloudflareaccess.com",
            "email": "operator@example.test",
            "status": {
                "admin_revision": int(self.approved),
                "binding_revision": int(self.approved),
                "active": False,
                "binding_matches_configuration": True,
                "generation": 0,
                "admin_fence": 0,
                "enrollments": [{"subject": "synthetic-verified-subject", "received_at": 1000.0}]
                if self.pending
                else [],
            },
        }

    def dispatch(self, payload):
        if payload.get("action") == "approve":
            self.approved = True
            return {
                "operation_id": payload["operation_id"],
                "action": "approve",
                "revision": 1,
                "binding_revision": 1,
                "fence": 0,
                "generation": 0,
                "active": False,
            }
        return {"verified": True}


class FixtureInventory:
    def __init__(self, clock):
        self.clock, self.failed = clock, False

    def records(self):
        return [
            RegisteredOperator(
                key=key,
                name=f"Operator {key.upper()}",
                email=f"{key}@example.test",
                hostname=f"{key}.example.test",
                release="release-20261028-01",
                profile="observed-profile",
                registered_revision=1,
            )
            for key in ("a", "b")
        ]

    def observe(self, section, instance):
        if self.failed or section == "recovery":
            raise OSError("private provider failure must never be rendered")
        if section == "capacity":
            return CapacitySnapshot(
                environment_hash="a" * 64,
                release="release-20261028-01",
                profile="observed-profile",
                observed=self.clock[0],
                memory_total=4000000000,
                memory_committed=2000000000,
                disk_total=30000000000,
                disk_free=20000000000,
                disk_committed=1000000000,
                recovery_staging=1000000000,
                active_count=2,
                inventory_clear=False,
                baseline_restored=False,
                test_resources_retired=False,
            )
        if section == "tunnel":
            return TunnelObservation(service="active", startup="disabled")
        if section == "discrepancies":
            return DiscrepancyObservation(unregistered=["c"], missing=[])
        if section == "runtime":
            return RuntimeObservation(service="active", mount_verified=True, release_matches=True)
        return AccessObservation(
            active=instance == "a",
            binding_matches=True,
            pending_enrollments=0 if instance == "a" else 1,
            starts=max(0.0, self.clock[0] - 3600),
            expires=self.clock[0] + 86400,
            capabilities=["records.read", "records.write"],
        )


def build_fixture(root, port):
    authority = AuthorityStore.initialize(
        root / "private" / "authority.sqlite", "Synthetic administrator"
    )
    clock = [time.time()]
    authority.clock = lambda: clock[0]
    inventory = FixtureInventory(clock)
    console = ConsoleReads(authority, inventory)
    setup_host = FixtureSetup()
    setup = SetupService(authority, setup_host)
    worker = SetupWorker(setup)

    app = create_admin_app(
        f"http://epm-admin.localhost:{port}",
        lambda value: authority.handle(
            BrokerRequest.model_validate(value), setup_host.dispatch, console, setup
        ),
        assets=Path(__file__).resolve().parents[1] / "apps/web/dist-admin",
    )

    @app.post("/__test/issue")
    async def issue():
        return {"credential": authority.issue()}

    @app.post("/__test/advance")
    async def advance(request: Request):
        clock[0] += (await request.json())["seconds"]
        return {"advanced": True}

    @app.post("/__test/revoke")
    async def revoke():
        authority.revoke_identity()
        return {"revoked": True}

    @app.post("/__test/restore")
    async def restore():
        authority.restore_identity()
        inventory.failed = False
        return {"restored": True}

    @app.post("/__test/observations")
    async def observations(request: Request):
        inventory.failed = (await request.json())["failed"]
        clock[0] += 31
        return {"updated": True}

    @app.post("/__test/operation")
    async def operation():
        credentials = authority.login(authority.issue())
        command = CommandRequest(
            operation_id=str(uuid4()),
            instance="b",
            action="disable",
            expected_revision=0,
            expected_binding_revision=0,
            fence=0,
            reason="Synthetic private containment",
            confirmed=True,
        )
        admission = authority.admit(BrokerRequest(method="command", command=command, **credentials))
        return {"id": admission["id"]}

    @app.post("/__test/finish")
    async def finish(request: Request):
        result = OperationEngine(authority).run(
            (await request.json())["id"], SourceEffect(lambda _: {"verified": True})
        )
        return result

    app.state.console = console
    app.state.inventory = inventory
    app.state.worker = worker

    install_setup_fixture(app, setup_host, setup, authority)

    return app


def install_setup_fixture(app, setup_host, setup, authority):
    @app.post("/__test/setup")
    async def setup_state(request: Request):
        values = await request.json()
        setup_host.allowed = values.get("allowed", setup_host.allowed)
        setup_host.provider_ready = values.get("provider_ready", setup_host.provider_ready)
        setup_host.pending = values.get("pending", setup_host.pending)
        return {"calls": setup_host.calls}

    @app.post("/__test/resume-grant")
    async def resume_grant(request: Request):
        with authority.transaction() as connection:
            operation = setup.engine._get(connection, (await request.json())["id"])
        return {"credential": authority.issue(setup.engine.resume_hash(operation))}

    @app.post("/__test/action-grant")
    async def action_grant(request: Request):
        command = CommandRequest.model_validate(await request.json())
        return {"credential": authority.issue(command.fingerprint())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="epm-private-admin-browser-") as directory:
        app = build_fixture(Path(directory), args.port)
        app.state.worker.start()
        try:
            uvicorn.run(
                app, host="127.0.0.1", port=args.port, proxy_headers=False, access_log=False
            )
        finally:
            app.state.worker.close()
            app.state.console.close()


if __name__ == "__main__":
    main()
