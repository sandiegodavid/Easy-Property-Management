"""Bounded per-network sliding-window rate limiter for unauthenticated /auth/start routes."""

from collections import OrderedDict, deque
from threading import Lock
import time

from fastapi import Request

from app.modules.hosted_access.application.managed_provider import ProviderUnavailable


class StartRateLimiter:
    """In-memory per-network limiter; never grows unbounded."""

    def __init__(
        self,
        *,
        limit: int = 60,
        window_seconds: float = 60.0,
        max_networks: int = 1024,
        clock=time.monotonic,
    ):
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_networks = max_networks
        self.clock = clock
        self._lock = Lock()
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()

    def network_key(self, request: Request) -> str:
        header = request.headers.get("x-epm-client-network")
        if header:
            return header.strip()
        if request.client is not None and request.client.host:
            return request.client.host
        return "unknown"

    def check(self, request: Request) -> None:
        key = self.network_key(request)
        now = self.clock()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                if len(self._hits) >= self.max_networks:
                    self._hits.popitem(last=False)
                bucket = deque()
                self._hits[key] = bucket
            else:
                self._hits.move_to_end(key)
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                raise ProviderUnavailable()
            bucket.append(now)
