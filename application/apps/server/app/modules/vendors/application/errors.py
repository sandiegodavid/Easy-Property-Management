"""Stable Provider application failures."""


class ProviderError(RuntimeError):
    pass


class ProviderNotFoundError(ProviderError):
    pass


class ProviderLifecycleConflict(ProviderError):
    def __init__(self, message, *, code="provider_conflict", current=None):
        super().__init__(message)
        self.code, self.current = code, current
