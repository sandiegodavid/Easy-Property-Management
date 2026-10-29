"""Disposable private-Admin browser fixture. Never install this helper on a host."""

import argparse
from pathlib import Path
import tempfile
import time
from uuid import uuid4

from fastapi import Request
import uvicorn

from app.modules.hosted_admin.api.application import create_admin_app
from app.modules.hosted_admin.application.contracts import BrokerRequest
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
    app = create_admin_app(
        f"http://epm-admin.localhost:{port}",
        lambda value: authority.handle(
            BrokerRequest.model_validate(value), lambda _: {"verified": True}, console
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

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="epm-private-admin-browser-") as directory:
        app = build_fixture(Path(directory), args.port)
        uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False, access_log=False)
        app.state.console.close()


if __name__ == "__main__":
    main()
