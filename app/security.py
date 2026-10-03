"""HTTP security boundary used by app.main.

This is intentionally small: one bearer token and an in-process write-rate
limit. Distributed deployments should move identity and rate limiting to a
gateway or shared infrastructure rather than treating this limiter as shared
state.
"""
from __future__ import annotations

import collections
import hmac
import threading
import time

from fastapi import HTTPException, Request

from .config import Settings


class RequestGuard:
    def __init__(self) -> None:
        self.hits: dict[str, collections.deque[float]] = collections.defaultdict(collections.deque)
        self._lock = threading.Lock()

    @staticmethod
    def _authorise(request: Request, settings: Settings) -> None:
        token = settings.api_token
        if not token:
            return
        auth = request.headers.get("authorization", "")
        scheme, _, credential = auth.partition(" ")
        valid = scheme.lower() == "bearer" and bool(credential) and hmac.compare_digest(credential, token)
        if not valid:
            raise HTTPException(401, "Missing or wrong bearer token.")

    @staticmethod
    def _client_key(request: Request) -> str:
        # Do not trust X-Forwarded-For here. A production ingress should enforce
        # its own distributed rate limit and trusted proxy policy.
        return request.client.host if request.client else "unknown"

    def read(self, request: Request, settings: Settings) -> None:
        self._authorise(request, settings)

    def write(self, request: Request, settings: Settings) -> None:
        self._authorise(request, settings)
        key = self._client_key(request)
        now = time.monotonic()
        with self._lock:
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= settings.rate_limit_per_minute:
                raise HTTPException(429, "Too many requests. Wait a minute and try again.")
            q.append(now)

    def clear(self) -> None:
        with self._lock:
            self.hits.clear()
