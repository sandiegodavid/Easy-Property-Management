"""Real Unix RPC must service status and priority fences while source effects stall."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from unittest.mock import Mock

import pytest

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.infrastructure import broker as transport
from app.modules.hosted_admin.infrastructure.private_operations import PrivateOperations
from app.modules.hosted_admin.infrastructure.operations import OperationEngine
from app.modules.hosted_admin.tests.test_authority import (
    authority as authority,
    command,
    login,
    request,
)


@contextmanager
def listening(broker, monkeypatch):
    # Short paths also work under macOS's Unix-socket path length limit. Only
    # installation ownership/kernel peer checks are simulated, never RPC or DB.
    with TemporaryDirectory(prefix="epm-rpc-", dir="/tmp") as directory:
        path = Path(directory) / "broker.sock"
        original_stat = Path.lstat
        original_serve = transport.BoundedUnixServer.serve_forever
        ready, servers, errors = threading.Event(), [], []

        def owner(candidate, *args, **kwargs):
            info = original_stat(candidate, *args, **kwargs)
            if candidate == path.parent:
                values = list(info)
                values[4] = 0
                return os.stat_result(values)
            return info

        def serve(server):
            servers.append(server)
            ready.set()
            original_serve(server, poll_interval=0.01)

        def run():
            try:
                broker.serve(path, os.getgid())
            except Exception as error:
                errors.append(error)
                ready.set()

        with monkeypatch.context() as patch:
            patch.setattr(Path, "lstat", owner)
            patch.setattr(transport.os, "chown", lambda *_: None)
            patch.setattr(transport.BoundedUnixServer, "serve_forever", serve)
            thread = threading.Thread(target=run)
            thread.start()
            try:
                assert ready.wait(5) and not errors
                yield path
            finally:
                if servers:
                    servers[0].shutdown()
                thread.join(timeout=5)
                assert not thread.is_alive() and not errors


class SlowSource:
    def __init__(self, count):
        self.entered = threading.Barrier(count + 1)
        self.release = threading.Event()
        self.results, self.contained = {}, set()

    def __call__(self, payload):
        self.entered.wait(timeout=10)
        assert self.release.wait(10)
        self.results[payload["operation_id"]] = {"done": True}
        return self.results[payload["operation_id"]]

    def reconcile(self, payload):
        return self.results.get(payload["operation_id"])

    def contain(self, payload):
        self.contained.add(payload["operation_id"])
        return True


def test_urgent_disable_bypasses_a_slow_approval_and_prevents_success(authority, monkeypatch):
    store, _ = authority

    class Source(SlowSource):
        def __call__(self, payload):
            if payload["action"] == "disable":
                self.results[payload["operation_id"]] = {"active": False}
                return self.results[payload["operation_id"]]
            return super().__call__(payload)

    source = Source(1)
    credentials = login(store)
    approve = command(action="approve", subject="verified", enrollment_received_at=1000.0)
    store.reauthenticate(
        request(
            credentials,
            approve,
            method="reauthenticate",
            credential=store.issue(approve.fingerprint()),
        )
    )
    original = request(credentials, approve)
    store.admit(original)
    broker = transport.Broker(store, 12345, source, peer=lambda _: 12345)
    with listening(broker, monkeypatch) as path, ThreadPoolExecutor(max_workers=2) as clients:
        future = clients.submit(transport.rpc, path, original.model_dump())
        try:
            source.entered.wait(timeout=10)
            disabled = clients.submit(
                transport.rpc, path, request(credentials, command()).model_dump()
            ).result(timeout=2)
            assert disabled == {"active": False}
            state = OperationEngine(store).get(approve.operation_id)
            assert state["cancel_requested"] == 1 and state["result"] is None
        finally:
            source.release.set()
        with pytest.raises(AdminError, match="fenced"):
            future.result(timeout=5)
    assert approve.operation_id in source.contained
    assert OperationEngine(store).get(approve.operation_id)["state"] == "paused"


@pytest.mark.parametrize("count", [1, transport.MAX_EFFECTS])
def test_status_and_revocation_bypass_slow_effects_and_fence_success(authority, monkeypatch, count):
    store, _ = authority
    source = SlowSource(count)
    operations = PrivateOperations(store, Mock(), source)
    broker = transport.Broker(store, 12345, source, peer=lambda _: 0, operations=operations)
    identifiers = []
    for index in range(count + 1):
        credentials = login(store)
        cmd = command(
            instance=f"demo-{index}",
            action="approve",
            subject="verified",
            enrollment_received_at=1000.0,
        )
        store.reauthenticate(
            request(
                credentials, cmd, method="reauthenticate", credential=store.issue(cmd.fingerprint())
            )
        )
        identifiers.append(store.admit(request(credentials, cmd))["id"])

    def rpc(path, action, identifier):
        return transport.rpc(
            path,
            {
                "method": "private_operations",
                "request": {"action": action, "identifier": identifier},
            },
        )

    with (
        listening(broker, monkeypatch) as path,
        ThreadPoolExecutor(max_workers=count + 1) as clients,
    ):
        futures = [
            clients.submit(rpc, path, "operation-run", identifier)
            for identifier in identifiers[:count]
        ]
        try:
            source.entered.wait(timeout=10)
            # The original synchronous server cannot answer either RPC until
            # the effect is released; the assertion deadlines prove ordering.
            status = clients.submit(rpc, path, "operation-status", identifiers[0]).result(timeout=2)
            assert status["state"] == "running"
            if count == transport.MAX_EFFECTS:
                with pytest.raises(AdminError, match="broker_busy"):
                    clients.submit(rpc, path, "operation-run", identifiers[-1]).result(timeout=2)
            assert clients.submit(transport.rpc, path, {"method": "revoke_identity"}).result(
                timeout=2
            ) == {"revoked": True}
            with store.transaction() as connection:
                assert connection.execute("SELECT enabled FROM administrator").fetchone()[0] == 0
        finally:
            source.release.set()
        for future in futures:
            with pytest.raises(AdminError, match="fenced"):
                future.result(timeout=5)
    for identifier in identifiers[:count]:
        result = OperationEngine(store).get(identifier)
        assert result["state"] == "paused" and result["result"] is None
        assert identifier in source.contained
        with store.transaction() as connection:
            assert (
                connection.execute(
                    "SELECT result FROM admission WHERE id=?", (identifier,)
                ).fetchone()[0]
                is None
            )
