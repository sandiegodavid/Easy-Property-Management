"""Trusted identity proofs are constructed only by qualified verifier adapters."""

from dataclasses import dataclass
from datetime import datetime


class HostedAccessError(ValueError):
    def __init__(self, code: str, message: str, status: int = 401):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    email: str
    issued_at: datetime
    expires_at: datetime
    fingerprint: str


@dataclass(frozen=True)
class HostedActor:
    operator_id: str
    workspace_id: str
    session_reference: str
    expires_at: datetime


@dataclass(frozen=True)
class SessionGrant:
    token: str
    csrf: str
    expires_at: datetime
