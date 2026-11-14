"""Bounded central revocation observations, shared across device proofs for one UID."""

from collections import OrderedDict
from dataclasses import dataclass
from threading import Event, Lock
import time

from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)

FRESH_MS = 300000
MAX_IDENTITIES = 128
MAX_WAIT_SECONDS = 5


@dataclass(frozen=True)
class UserStatus:
    subject: str
    disabled: bool
    valid_since: int


@dataclass(frozen=True)
class StatusObservation:
    status: UserStatus
    checked_at: int
    valid_until: int


class RevocationCache:
    """No provider call on cache hits; one bounded in-flight check per realm/UID.

    Failures retain no invented freshness. Old proofs and fresh proofs share account
    status, but each is independently compared against the retained valid-since fence.
    """

    def __init__(self, fetch, *, clock=time.time):
        self.fetch, self.clock = fetch, clock
        self.records = OrderedDict()
        self.pending = {}
        self.lock = Lock()

    def observe(self, identity):
        return self._check(self.account_status(identity), identity, int(self.clock() * 1000))

    def account_status(self, identity):
        """Observe the account even when it is disabled or its valid-since advanced."""
        key = (identity.realm, identity.subject)
        with self.lock:
            now = int(self.clock() * 1000)
            previous = self.records.get(key)
            if previous is not None and now < previous.checked_at + FRESH_MS:
                self.records.move_to_end(key)
                return previous
            waiting = self.pending.get(key)
            leader = waiting is None
            if leader:
                if len(self.pending) >= MAX_IDENTITIES:
                    raise ProviderUnavailable()
                waiting = Event()
                self.pending[key] = waiting
        if not leader:
            if not waiting.wait(MAX_WAIT_SECONDS):
                raise ProviderUnavailable()
            with self.lock:
                record = self.records.get(key)
            if record is None:
                raise ProviderUnavailable()
            return record
        try:
            checked_at = int(self.clock() * 1000)
            status = self.fetch(identity)
            record = StatusObservation(status, checked_at, checked_at + FRESH_MS)
            with self.lock:
                self.records[key] = record
                self.records.move_to_end(key)
                while len(self.records) > MAX_IDENTITIES:
                    self.records.popitem(last=False)
            return record
        finally:
            with self.lock:
                self.pending.pop(key, None)
                waiting.set()

    @staticmethod
    def _check(record, identity, now):
        if record.status.subject != identity.subject:
            raise ProviderDenied()
        until = min(record.checked_at + FRESH_MS, identity.expires_at)
        if not record.checked_at <= now < until:
            raise ProviderUnavailable()
        if record.status.disabled or identity.authenticated_at < record.status.valid_since:
            raise ProviderDenied()
        return StatusObservation(record.status, record.checked_at, until)
