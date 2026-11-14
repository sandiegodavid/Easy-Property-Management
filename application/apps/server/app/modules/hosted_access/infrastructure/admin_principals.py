"""Read Admin admission from the owning store without provisioning on sign-in."""

import json
from typing import Literal
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.modules.hosted_access.application.admin_admission import AdminPrincipal
from app.modules.hosted_access.application.identity_setup import IdentityRealm


class SQLiteAdminPrincipalReader:
    def __init__(self, engine: Engine):
        self.engine = engine

    def by_identity(self, issuer: str, subject: str) -> AdminPrincipal | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT principal_id, enabled, session_generation FROM main.admin_principals "
                    "WHERE issuer = :issuer AND subject = :subject"
                ),
                {"issuer": issuer, "subject": subject},
            ).one_or_none()
        if row is None:
            return None
        return AdminPrincipal(row.principal_id, row.enabled == 1, row.session_generation)


def change_admin_principal(
    connection: Connection,
    *,
    realm: IdentityRealm,
    subject: str,
    action: Literal["bootstrap", "suspend", "restore"],
    now: int,
    expected_revision: int | None = None,
) -> str:
    """Apply one explicit platform-owner decision inside the store's write reservation."""
    if not 1 <= len(subject) <= 128 or any(ord(char) < 33 for char in subject):
        raise ValueError("A valid provider subject is required.")
    identity = {"issuer": realm.alias, "subject": subject}
    current = connection.execute(
        text(
            "SELECT principal_id, enabled, revision FROM main.admin_principals "
            "WHERE issuer = :issuer AND subject = :subject"
        ),
        identity,
    ).one_or_none()

    if action == "bootstrap":
        if expected_revision is not None:
            raise ValueError("Bootstrap does not accept a revision.")
        if current is not None:
            if not current.enabled:
                raise ValueError("A suspended principal requires explicit restoration.")
            return current.principal_id
        principal_id = str(uuid4())
        connection.execute(
            text(
                "INSERT INTO main.admin_principals "
                "(principal_id, issuer, subject, enabled, session_generation, revision, created_at) "
                "VALUES (:id, :issuer, :subject, 1, 1, 1, :now)"
            ),
            identity | {"id": principal_id, "now": now},
        )
    elif action in {"suspend", "restore"}:
        if current is None or expected_revision is None:
            raise ValueError("Recovery requires an existing principal and its revision.")
        principal_id = current.principal_id
        enabled = action == "restore"
        if current.revision != expected_revision or bool(current.enabled) == enabled:
            raise ValueError("The principal has changed. Review current state before retrying.")
        connection.execute(
            text(
                "UPDATE main.admin_principals SET enabled = :enabled, revision = revision + 1, "
                "session_generation = session_generation + 1 WHERE principal_id = :id"
            ),
            {"id": principal_id, "enabled": enabled},
        )
    else:
        raise ValueError("Unknown Admin principal action.")

    connection.execute(
        text(
            "INSERT INTO main.admin_audit "
            "(audit_id, actor_ref, action, recorded_at, safe_facts_json) "
            "VALUES (:id, 'platform-owner', :action, :now, :facts)"
        ),
        {
            "id": str(uuid4()),
            "action": f"admin_principal_{action}",
            "now": now,
            "facts": json.dumps({"principal_id": principal_id}),
        },
    )
    return principal_id
