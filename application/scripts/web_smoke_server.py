"""Serve wheel assets with production FastAPI and disposable external workspaces."""

import argparse
import json
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import uvicorn
from pydantic import BaseModel, Field
import app.modules.leases.application.service as lease_service

from app.bootstrap.api import create_app
from app.modules.workspace.application.service import WorkspaceService
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.portfolio.application.service import (
    PortfolioService,
    PropertyCreateCommand,
    OwnershipInput,
)
from app.modules.parties.application.service import PartyCreateCommand
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioUnitOfWork
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver

APPLICATION = Path(__file__).resolve().parents[1]


class LeaseClock(BaseModel):
    days: int = Field(ge=0, le=2)


class LeaseDateType(type):
    def __instancecheck__(cls, value):
        return isinstance(value, date)


class BrowserLeaseDate(date, metaclass=LeaseDateType):
    offset = 0

    @classmethod
    def today(cls):
        return date.today() + timedelta(days=cls.offset)


def lease_instant():
    return (datetime.now(UTC) + timedelta(days=BrowserLeaseDate.offset)).isoformat()


_lease_date = lease_service._date


def lease_date(value, label):
    # HTTP Pydantic dates remain real dates when the lifecycle clock is advanced.
    return _lease_date(value.isoformat() if isinstance(value, date) else value, label)


def register_historical_owner_fixture(app, config, state):
    if state == "ready":

        @app.post("/__test__/historical-owner", include_in_schema=False)
        def historical_owner():
            workspace = WorkspaceService.from_local_config(config)
            yesterday = datetime.now(ZoneInfo("America/Los_Angeles")) - timedelta(days=1)
            instant = yesterday.replace(hour=12, minute=0, second=0, microsecond=0).astimezone(UTC)
            recorder = AuditRecorder(SQLiteAuditRepository(workspace.paths.database))
            portfolio = PortfolioService(
                SQLitePortfolioUnitOfWork(workspace.paths.database, recorder),
                time_zone_resolver=BundledAddressTimeZoneResolver(),
                now=lambda: instant,
            )
            return portfolio.create_property(
                PropertyCreateCommand(
                    "Historical reporter home",
                    "2 Main Street",
                    "Portland",
                    "US",
                    "single_family_home",
                    (
                        OwnershipInput(
                            "client_owner",
                            inline_party=PartyCreateCommand(
                                "individual", f"Historical owner {uuid4()}"
                            ),
                        ),
                    ),
                    region="OR",
                ),
                expected_revision=0,
                idempotency_key=str(uuid4()),
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state", choices=("ready", "unavailable"), required=True)
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    context = (
        nullcontext(str(args.directory))
        if args.directory
        else TemporaryDirectory(prefix="epm-browser-")
    )
    with context as directory:
        root = Path(directory).resolve()
        config = root / "config.json"
        if not config.exists():
            config.write_text(json.dumps({"localWorkspacePath": str(root / "workspace")}))
            if args.state == "ready":
                WorkspaceService.from_local_config(config).initialize()
        wheel = APPLICATION / "dist/easy_property_management-0.1.0-py3-none-any.whl"
        web = root / "web_build"
        with ZipFile(wheel) as archive:
            for name in archive.namelist():
                if name.startswith("app/web_build/"):
                    relative = Path(name).relative_to("app/web_build")
                    if ".." in relative.parts:
                        raise RuntimeError("Unsafe wheel asset")
                    destination = web / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    content = archive.read(name)
                    if content != (APPLICATION / "apps/web/dist" / relative).read_bytes():
                        raise RuntimeError("Wheel assets differ from the current Vite build")
                    destination.write_bytes(content)
        app = create_app(config, web_build_path=web)
        register_historical_owner_fixture(app, config, args.state)

        # Isolated smoke-server clock control; never registered in the product API.
        lease_service.date = BrowserLeaseDate
        lease_service._now = lease_instant
        lease_service._date = lease_date

        @app.post("/__test__/lease-clock", include_in_schema=False)
        def lease_clock(command: LeaseClock):
            BrowserLeaseDate.offset = command.days
            return {"effectiveOn": BrowserLeaseDate.today().isoformat()}

        uvicorn.run(
            app,
            host="127.0.0.1",
            port=args.port,
            proxy_headers=False,
        )
        if args.state == "unavailable" and (root / "workspace").exists():
            raise AssertionError("Browser delivery initialized the unavailable workspace")


if __name__ == "__main__":
    main()
