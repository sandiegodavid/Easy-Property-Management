"""Focused installed-candidate checks inside isolated Linux containers, never live data."""

import argparse
from http.client import HTTPConnection
from http.server import HTTPServer
from importlib import import_module
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread

from app.hosted_candidates.runtime import HostedStatusHandler, inspect
from app.platform.config import application_root
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore, SchemaResourcesUnavailable


UNAVAILABLE_EXIT = 3


def health():
    with HTTPServer(("127.0.0.1", 0), HostedStatusHandler) as server:
        server.binding = None
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            statuses = {}
            for route in ("/health/live", "/health/ready", "/api/properties", "/"):
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("GET", route)
                response = connection.getresponse()
                statuses[route] = response.status
                body = response.read()
                if route == "/":
                    assert b"Temporarily unavailable" in body
                    assert b"<script" not in body and b"<form" not in body
                elif route == "/health/live":
                    assert json.loads(body) == {"status": "alive"}
                else:
                    assert json.loads(body)["ready"] is False
                assert response.getheader("Cache-Control") == "no-store"
                connection.close()
            assert statuses == {
                "/health/live": 200,
                "/health/ready": 503,
                "/api/properties": 503,
                "/": 503,
            }
            return statuses
        finally:
            server.shutdown()
            thread.join(timeout=5)


def probe(component):
    report = inspect(component)
    assert Path.cwd() == Path("/tmp")
    assert all(shutil.which(name) is None for name in ("gcc", "g++", "clang", "cc"))
    stores = {
        "admin": ("admin", "admin-recovery"),
        "operator": ("business", "hosted-access", "recovery"),
        "host_agent": ("host-inventory",),
    }[component]
    resources = {}
    with TemporaryDirectory(prefix="epm-installed-") as directory:
        for store in stores:
            path = Path(directory) / f"{store}.sqlite"
            if store == "business":
                business = import_module("app.platform.product_migrations")
                business.initialize_latest_schema(path)
                business.validate_latest_schema(path)
                resources[store] = "initialized_validated"
            else:
                try:
                    first = initialize_store(
                        HostedStore(store), path, application_directory=application_root()
                    )
                except SchemaResourcesUnavailable:
                    assert not path.exists()
                    resources[store] = "unavailable_no_destination_created"
                    continue
                before = path.read_bytes()
                again = initialize_store(
                    HostedStore(store), path, application_directory=application_root()
                )
                assert first.value == "initialized" and again.value == "already_initialized"
                assert path.read_bytes() == before
                resources[store] = "initialized_read_only_reinit"
            with sqlite3.connect(path) as connection:
                if store != "business":
                    tables = connection.execute(
                        "SELECT name FROM sqlite_schema "
                        "WHERE type='table' AND name!='alembic_version'"
                    ).fetchall()
                    assert all(
                        connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0] == 0
                        for (name,) in tables
                    )
        module = {"admin": "admin", "operator": "operator", "host_agent": "agent"}[component]
        blocked = subprocess.run(
            [sys.executable, "-B", "-m", "app.hosted_candidates." + module],
            capture_output=True,
            text=True,
            check=False,
        )
        assert blocked.returncode == UNAVAILABLE_EXIT and "unavailable" in blocked.stderr
    return {
        "candidate": report,
        "resources": resources,
        "health": health() if component != "host_agent" else None,
        "python": platform.python_version(),
        "machine": platform.machine(),
        "system": platform.system(),
        "normalStartup": "blocked",
        "compiler": "absent",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=("admin", "operator", "host_agent"), required=True)
    args = parser.parse_args()
    print(json.dumps(probe(args.component), sort_keys=True))
