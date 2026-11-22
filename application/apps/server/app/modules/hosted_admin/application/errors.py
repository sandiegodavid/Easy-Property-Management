"""Typed errors for the hosted Admin-lite control plane."""

from __future__ import annotations


class AdminControlError(RuntimeError):
    """Base error with safe machine code and HTTP status mapping."""

    def __init__(self, code: str, message: str, *, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class AdminDeniedError(AdminControlError):
    """Caller authority, MFA freshness, or state fence was not satisfied."""

    def __init__(
        self,
        code: str = "admin_authority_denied",
        message: str = "Admin action denied.",
    ) -> None:
        super().__init__(code, message, status=403)


class AdminNotFoundError(AdminControlError):
    """Referenced operator, release, policy, or operation does not exist."""

    def __init__(
        self,
        code: str = "admin_resource_not_found",
        message: str = "Resource not found.",
    ) -> None:
        super().__init__(code, message, status=404)


class AdminConflictError(AdminControlError):
    """Unique constraint, revision fence, or capacity headroom rejected the command."""

    def __init__(
        self,
        code: str = "admin_conflict",
        message: str = "The requested change conflicts with current state.",
        *,
        limiting_resources: tuple[str, ...] = (),
    ) -> None:
        super().__init__(code, message, status=409)
        self.limiting_resources = limiting_resources


class AdminUnavailableError(AdminControlError):
    """Capacity snapshot or required dependency is stale or unavailable."""

    def __init__(
        self,
        code: str = "admin_service_unavailable",
        message: str = "The requested administrative check is currently unavailable.",
    ) -> None:
        super().__init__(code, message, status=503)
