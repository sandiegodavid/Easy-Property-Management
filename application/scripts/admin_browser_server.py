"""Disposable private-Admin browser fixture. Never install this helper on a host."""

import argparse
from pathlib import Path
import tempfile
import time

from fastapi import Request
import uvicorn

from app.modules.hosted_admin.api.application import create_admin_app
from app.modules.hosted_admin.application.contracts import BrokerRequest
from app.modules.hosted_admin.infrastructure.authority import AuthorityStore


def build_fixture(root, port):
    authority = AuthorityStore.initialize(
        root / "private" / "authority.sqlite", "Synthetic administrator"
    )
    clock = [time.time()]
    authority.clock = lambda: clock[0]
    app = create_admin_app(
        f"http://epm-admin.localhost:{port}",
        lambda value: authority.handle(
            BrokerRequest.model_validate(value), lambda _: {"committed": True}
        ),
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
        return {"restored": True}

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="epm-private-admin-browser-") as directory:
        app = build_fixture(Path(directory), args.port)
        uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False, access_log=False)


if __name__ == "__main__":
    main()
