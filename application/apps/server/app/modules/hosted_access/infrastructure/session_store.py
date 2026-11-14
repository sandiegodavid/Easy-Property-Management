"""Fail-closed import guard for the retired Cloudflare/demo session composition.

Keep the historical name for bootstrap, administration and recovery imports until
those compositions are replaced. Never inspect, open, initialize or mutate a store,
including a store already initialized with the current owning schema.
"""

from typing import NoReturn

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.domain.models import HostedAccessError


def _unavailable() -> NoReturn:
    raise HostedAccessError(
        "hosted_access_unavailable",
        "Hosted sign-in is unavailable.",
        503,
    )


class SQLiteHostedSessionStore:
    """Legacy entry guard only; this class grants no session or edit authority."""

    def __init__(self, deployment: HostedDeployment):
        _unavailable()

    @staticmethod
    def initialize(deployment: HostedDeployment) -> NoReturn:
        _unavailable()
