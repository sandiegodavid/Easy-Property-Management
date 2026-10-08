"""Stable Tenant application failures."""


class TenantError(RuntimeError):
    pass


class TenantNotFoundError(TenantError):
    pass


class TenantConflictError(TenantError):
    def __init__(self, message, *, code="tenant_conflict", current=None):
        super().__init__(message)
        self.code = code
        self.current = current
