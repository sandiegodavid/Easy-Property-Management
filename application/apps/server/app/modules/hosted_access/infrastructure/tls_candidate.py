"""Launch identity listeners with actual upstream TLS and no forwarding trust."""

import uvicorn

from app.modules.hosted_access.infrastructure.admin_bootstrap import private_file


def run_identity_tls(app, address, args):
    private_file(args.tls_key)
    if not 1 <= args.port <= 65535:
        raise ValueError("Invalid identity listener port.")
    uvicorn.run(
        app,
        host=str(address),
        port=args.port,
        proxy_headers=False,
        access_log=False,
        ssl_keyfile=str(args.tls_key),
        ssl_certfile=str(args.tls_certificate),
        ws="none",
    )
