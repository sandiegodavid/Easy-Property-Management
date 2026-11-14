"""Durable central attempt and email-code reservations in the existing Admin store."""

from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.modules.hosted_access.application.central_login import SourceLoginContext
from app.modules.hosted_access.application.identity_setup import MINUTE
from app.modules.hosted_access.application.managed_provider import ProviderDenied, email_key
from app.platform.sqlite_engine import immediate_transaction


def digest(value):
    return sha256(value.encode()).hexdigest()


class CentralAttempts:
    def __init__(self, engine, setup, source, *, clock):
        self.engine, self.setup, self.source, self.clock = engine, setup, source, clock

    def start(self, flow_id, *, method, email=None, origin_id=None):
        if method not in {"google", "email_link"}:
            raise ProviderDenied()
        context = (
            self.source.resolve_start(flow_id, origin_id=origin_id)
            if origin_id is not None
            else self.source.resolve_start(flow_id)
        )
        self.source.current(context)
        if not isinstance(context, SourceLoginContext):
            raise ProviderDenied()
        browser, attempt_id = token_urlsafe(32), str(uuid4())
        now = self.clock()
        recipient = email_key(self.setup.realm.alias, email) if method == "email_link" else None
        with immediate_transaction(self.engine) as connection:
            assignment = self.assignment(connection, context)
            if recipient is not None and recipient != assignment["email_key"]:
                raise ProviderDenied()
            if context.expires_at <= now:
                raise ProviderDenied()
            count = connection.scalar(
                text(
                    "SELECT count(*) FROM main.login_attempts WHERE operator_id=:id "
                    "AND state IN ('pending','verified') AND expires_at>:now"
                ),
                {"id": context.operator_id, "now": now},
            )
            if count >= 32:
                raise ProviderDenied()
            connection.execute(
                text("""
                INSERT INTO main.login_attempts (
                    attempt_id, purpose, operator_id, parent_managed_session_id, source_attempt_id, source_browser_hash,
                    central_browser_hash, method, email_key, target_origin, return_path,
                    state, created_at, expires_at, revision
                ) VALUES (:id, :purpose, :operator, :parent, :source, :source_hash,
                          :browser, :method, :email, :origin, :path, 'pending', :now, :expires, 1)
            """),
                {
                    "id": attempt_id,
                    "operator": context.operator_id,
                    "purpose": "renewal" if context.renewal is not None else "operator_login",
                    "parent": context.renewal.managed_session_id
                    if context.renewal is not None
                    else None,
                    "source": context.source_attempt_id,
                    "source_hash": context.source_browser_hash,
                    "browser": digest(browser),
                    "method": method,
                    "email": recipient,
                    "origin": context.target_origin,
                    "path": context.return_path,
                    "now": now,
                    "expires": min(now + 15 * MINUTE, context.expires_at),
                },
            )
        return attempt_id, browser

    def assignment(self, connection, context):
        row = (
            connection.execute(
                text("SELECT * FROM main.operators WHERE operator_id=:id"),
                {"id": context.operator_id},
            )
            .mappings()
            .one_or_none()
        )
        if (
            row is None
            or row["desired_access"] == "retired"
            or row["access_epoch"] != context.access_epoch
            or row["revision"] != context.assignment_revision
            or row["issuer"] != self.setup.realm.alias
        ):
            raise ProviderDenied()
        return row

    def attempt(self, connection, attempt_id, browser=None):
        row = (
            connection.execute(
                text("SELECT * FROM main.login_attempts WHERE attempt_id=:id"), {"id": attempt_id}
            )
            .mappings()
            .one_or_none()
        )
        if (
            row is None
            or row["purpose"] not in {"operator_login", "renewal"}
            or row["method"] not in {"google", "email_link"}
            or not row["created_at"] <= self.clock() < row["expires_at"]
        ):
            raise ProviderDenied()
        if browser is not None and (
            not isinstance(browser, str)
            or len(browser) != 43
            or not compare_digest(row["central_browser_hash"], digest(browser))
        ):
            raise ProviderDenied()
        return row

    def reserve_google(self, attempt_id, browser):
        with immediate_transaction(self.engine) as connection:
            row = self.attempt(connection, attempt_id, browser)
            if row["method"] != "google" or row["state"] != "pending":
                raise ProviderDenied()
            connection.execute(
                text(
                    "UPDATE main.login_attempts SET state='verified', revision=revision+1 "
                    "WHERE attempt_id=:id"
                ),
                {"id": attempt_id},
            )
            return dict(row)

    def reserve_email(self, attempt_id, browser, code):
        if not isinstance(browser, str) or len(browser) != 43:
            raise ProviderDenied()
        if not 1 <= len(code.get_secret_value()) <= 2048:
            raise ProviderDenied()
        code_hash = digest(self.setup.realm.alias + ":" + code.get_secret_value())
        now = self.clock()
        try:
            with immediate_transaction(self.engine) as connection:
                attempt = self.attempt(connection, attempt_id)
                if attempt["method"] != "email_link":
                    raise ProviderDenied()
                prior = (
                    connection.execute(
                        text(
                            "SELECT * FROM main.email_continuations "
                            "WHERE original_attempt_id=:id OR code_hash=:hash"
                        ),
                        {"id": attempt_id, "hash": code_hash},
                    )
                    .mappings()
                    .all()
                )
                if prior:
                    if (
                        len(prior) != 1
                        or prior[0]["original_attempt_id"] != attempt_id
                        or prior[0]["code_hash"] != code_hash
                        or not prior[0]["created_at"] <= now < prior[0]["expires_at"]
                        or not compare_digest(prior[0]["central_browser_hash"], digest(browser))
                    ):
                        raise ProviderDenied()
                    return dict(prior[0]), False
                if attempt["state"] != "pending":
                    raise ProviderDenied()
                operator = connection.execute(
                    text("SELECT access_epoch FROM main.operators WHERE operator_id=:id"),
                    {"id": attempt["operator_id"]},
                ).one()
                identifier = str(uuid4())
                connection.execute(
                    text("""
                    INSERT INTO main.email_continuations (
                        continuation_id, original_attempt_id, code_hash, central_browser_hash,
                        operator_id, target_origin, access_epoch, state, created_at, expires_at, revision
                    ) VALUES (:id, :attempt, :code, :browser, :operator, :origin,
                              :epoch, 'verifying', :now, :expires, 1)
                """),
                    {
                        "id": identifier,
                        "attempt": attempt_id,
                        "code": code_hash,
                        "browser": digest(browser),
                        "operator": attempt["operator_id"],
                        "origin": attempt["target_origin"],
                        "epoch": operator.access_epoch,
                        "now": now,
                        "expires": min(now + 5 * MINUTE, attempt["expires_at"]),
                    },
                )
                row = (
                    connection.execute(
                        text("SELECT * FROM main.email_continuations WHERE continuation_id=:id"),
                        {"id": identifier},
                    )
                    .mappings()
                    .one()
                )
                return dict(row), True
        except IntegrityError:
            raise ProviderDenied() from None

    def mark_email_unknown(self, continuation_id):
        with immediate_transaction(self.engine) as connection:
            connection.execute(
                text(
                    "UPDATE main.email_continuations SET state='unknown', revision=revision+1 "
                    "WHERE continuation_id=:id AND state='verifying'"
                ),
                {"id": continuation_id},
            )

    def current_context(self, attempt):
        context = self.source.inspect_start(attempt["operator_id"], attempt["source_attempt_id"])
        if (
            not isinstance(context, SourceLoginContext)
            or context.operator_id != attempt["operator_id"]
            or context.source_attempt_id != attempt["source_attempt_id"]
            or context.source_browser_hash != attempt["source_browser_hash"]
            or context.target_origin != attempt["target_origin"]
            or context.expires_at <= self.clock()
        ):
            raise ProviderDenied()
        self.source.current(context)
        return context
