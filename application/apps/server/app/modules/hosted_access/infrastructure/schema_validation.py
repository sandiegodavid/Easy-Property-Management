"""Retained H03 record validation in a caller-owned snapshot, without remote calls."""

import json

from app.modules.hosted_access.application.identity_evidence import (
    IdentityCommandState,
    SessionReceipt,
)
from app.modules.hosted_access.application.identity_states import (
    AccessSessionState,
    AdminSessionState,
    EmailContinuationState,
    LoginAttemptState,
    LoginHandoffState,
    ManagedIdentitySessionState,
    SourceLoginAttemptState,
)
from app.modules.hosted_access.application.source_contracts import SourceResult
from app.platform.schema_resources import HostedStore

ADMIN_MODELS = {
    "login_attempts": LoginAttemptState,
    "email_continuations": EmailContinuationState,
    "managed_identity_sessions": ManagedIdentitySessionState,
    "login_handoffs": LoginHandoffState,
    "admin_sessions": AdminSessionState,
}
SOURCE_MODELS = {
    "access_sessions": AccessSessionState,
    "source_login_attempts": SourceLoginAttemptState,
}
SESSION_KINDS = {"issue_session", "refresh_session", "revoke_session"}


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate identity result field.")
        result[key] = value
    return result


def _json(value):
    return json.loads(value, object_pairs_hook=_unique_fields)


def validate_identity_records(connection, store):
    """Constant query count, streamed rows; no writer, provider call or readiness grant.

    Executable DDL enforces local constraints. These checks cover typed JSON, encoded
    return paths and relationships which cannot be expressed by a SQLite row CHECK.
    Historical stale/revoked rows remain valid data; this is not request admission.
    """
    if store not in {HostedStore.ADMIN, HostedStore.HOSTED_ACCESS}:
        return
    models = ADMIN_MODELS if store == HostedStore.ADMIN else SOURCE_MODELS
    for table, model in models.items():
        for row in connection.exec_driver_sql(f"SELECT * FROM main.{table}").mappings():
            fields = dict(row)
            if table in {"source_login_attempts", "access_sessions"}:
                fields["remembered"] = bool(fields["remembered"])
            model.model_validate(fields)
    if store == HostedStore.ADMIN:
        _identity_commands(connection)
        _admin_relationships(connection)
    else:
        _source_receipts(connection)


def _identity_commands(connection):
    for row in connection.exec_driver_sql("SELECT * FROM main.identity_commands").mappings():
        fields = dict(row)
        raw = fields.pop("result_json")
        fields["result"] = _json(raw) if raw is not None else None
        IdentityCommandState.model_validate(fields)


def _source_receipts(connection):
    for row in connection.exec_driver_sql("SELECT * FROM main.access_receipts").mappings():
        fields = _json(row["result_json"])
        if row["kind"] in SESSION_KINDS:
            receipt = SessionReceipt.model_validate(fields)
            if (
                receipt.kind != row["kind"]
                or receipt.operation_id != row["operation_id"]
                or receipt.request_hash != row["request_hash"]
                or receipt.binding.access_epoch != row["access_epoch"]
                or receipt.source_revision != row["source_revision"]
            ):
                raise ValueError("Session receipt does not retain its original intent/fences.")
        else:
            result = SourceResult.model_validate(fields)
            if result.access_epoch != row["access_epoch"]:
                raise ValueError("Control receipt does not retain its original access fence.")


def _admin_relationships(connection):
    invalid = connection.exec_driver_sql("""
        SELECT 1 FROM main.admin_sessions s
        JOIN main.managed_identity_sessions m ON m.managed_session_id=s.managed_session_id
        JOIN main.admin_principals p ON p.principal_id=s.principal_id
        WHERE m.purpose!='admin' OR p.issuer!=m.issuer OR p.subject!=m.subject
          OR s.authenticated_at!=m.authenticated_at OR s.mfa_verified_at!=m.mfa_verified_at
          OR s.managed_valid_until>m.provider_valid_until
          OR s.revocation_valid_until>m.revocation_valid_until
        UNION ALL
        SELECT 1 FROM main.identity_commands c
        JOIN main.managed_identity_sessions m ON m.managed_session_id=c.managed_session_id
        LEFT JOIN main.login_attempts a ON a.attempt_id=c.attempt_id
        WHERE c.operator_id IS NOT m.operator_id
           OR (c.attempt_id IS NOT NULL AND a.operator_id IS NOT c.operator_id)
        UNION ALL
        SELECT 1 FROM main.login_attempts a
        JOIN main.managed_identity_sessions m ON m.managed_session_id=a.parent_managed_session_id
        WHERE a.operator_id IS NOT m.operator_id
        UNION ALL
        SELECT 1 FROM main.login_attempts a
        JOIN main.managed_identity_sessions m ON m.managed_session_id=a.completed_managed_session_id
        WHERE a.operator_id IS NOT m.operator_id OR m.method!='google' OR m.purpose!='operator'
        UNION ALL
        SELECT 1 FROM main.login_handoffs h
        JOIN main.managed_identity_sessions m ON m.managed_session_id=h.managed_session_id
        JOIN main.login_attempts a ON a.attempt_id=h.attempt_id
        JOIN main.identity_commands c ON c.operation_id=h.identity_operation_id
        WHERE m.purpose!='operator' OR m.operator_id!=h.operator_id
          OR a.operator_id IS NOT h.operator_id OR c.operator_id IS NOT h.operator_id
          OR c.managed_session_id!=h.managed_session_id OR c.attempt_id IS NOT h.attempt_id
          OR a.source_browser_hash IS NOT h.browser_state_hash OR a.target_origin!=h.target_origin
          OR h.expires_at>a.expires_at OR h.expires_at>m.provider_valid_until
          OR (h.issuer IS NOT NULL AND (h.issuer!=m.issuer OR h.subject!=m.subject))
        UNION ALL
        SELECT 1 FROM main.email_continuations e
        JOIN main.login_attempts a ON a.attempt_id=e.original_attempt_id
        LEFT JOIN main.managed_identity_sessions m ON m.managed_session_id=e.managed_session_id
        WHERE a.method!='email_link' OR a.operator_id IS NOT e.operator_id
          OR a.target_origin!=e.target_origin OR e.expires_at>a.expires_at
          OR (e.managed_session_id IS NOT NULL AND (m.purpose!='operator'
              OR m.operator_id IS NOT e.operator_id OR m.method!='email_link'
              OR m.email_key IS NOT a.email_key OR e.expires_at>m.provider_valid_until))
        LIMIT 1
    """).first()
    if invalid is not None:
        raise ValueError("Retained identity relationships do not match their owning records.")
