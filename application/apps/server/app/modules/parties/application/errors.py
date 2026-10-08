"""Typed shared Party command failures."""


class PartyValidationError(ValueError):
    pass


class PartyNotFoundError(PartyValidationError):
    pass


class PartyConflictError(PartyValidationError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "party_conflict",
        current: dict | None = None,
        current_tenant: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.current = current
        self.current_tenant = current_tenant
