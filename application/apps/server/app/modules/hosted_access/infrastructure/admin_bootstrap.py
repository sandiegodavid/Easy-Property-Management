"""Offline platform-owner CLI. Run under the protected Admin store owner."""

import argparse
import os
from pathlib import Path
import stat
from time import time_ns

from sqlalchemy import text

from app.modules.hosted_access.application.identity_setup import IdentitySetup
from app.modules.hosted_access.infrastructure.admin_principals import change_admin_principal
from app.platform.hosted_schema import validate_schema
from app.platform.hosted_writer_lock import HostedWriterLock
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction


def private_file(path: Path) -> None:
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("Use a canonical private path.")
    file = path.stat()
    directory = path.parent.stat()
    if (
        not stat.S_ISREG(file.st_mode)
        or file.st_nlink != 1
        or file.st_uid != os.geteuid()
        or directory.st_uid != os.geteuid()
        or (file.st_mode | directory.st_mode) & 0o077
    ):
        raise ValueError("The Admin store owner must control the private input files.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "bootstrap", "suspend", "restore"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--writer-lock", type=Path, required=True)
    parser.add_argument("--setup", type=Path, required=True)
    parser.add_argument("--application-directory", type=Path, required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--expected-revision", type=int)
    args = parser.parse_args()

    private_file(args.database)
    private_file(args.setup)
    setup = IdentitySetup.model_validate_json(args.setup.read_bytes())
    with HostedWriterLock(args.writer_lock):
        engine = create_sqlite_engine(args.database)
        try:
            with immediate_transaction(engine) as connection:
                validate_schema(
                    connection, HostedStore.ADMIN, application_directory=args.application_directory
                )
                if args.action != "inspect":
                    change_admin_principal(
                        connection,
                        realm=setup.realm,
                        subject=args.subject,
                        action=args.action,
                        now=time_ns() // 1_000_000,
                        expected_revision=args.expected_revision,
                    )
                principal = connection.execute(
                    text(
                        "SELECT principal_id, enabled, revision FROM main.admin_principals "
                        "WHERE issuer = :issuer AND subject = :subject"
                    ),
                    {"issuer": setup.realm.alias, "subject": args.subject},
                ).one_or_none()
                if principal is None:
                    parser.exit(1, "Admin principal was not found.\n")
        finally:
            engine.dispose()
    state = "enabled" if principal.enabled else "suspended"
    print(f"{principal.principal_id} {state} revision {principal.revision}")


if __name__ == "__main__":
    main()
