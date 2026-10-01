"""Authentication and simple in-process POST rate limiting."""
from __future__ import annotations
import collections
import threading
import time
from fastapi import HTTPException, Request

class RequestGuard:
    def __init__(self, settings):
        self.settings = settings
        self.hits: dict[str, collections.deque] = collections.defaultdict(collections.deque)
        self.lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        if self.settings.api_token:
            auth = request.headers.get("authorization", "")
            if auth != f"Bearer {self.settings.api_token}":
                raise HTTPException(401, "Missing or wrong token. Send Authorization: Bearer <API_TOKEN>.")
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self.lock:
            q = self.hits[ip]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.settings.rate_limit_per_minute:
                raise HTTPException(429, "Too many requests. Wait a minute and try again.")
            q.append(now)

    def clear(self) -> None:
        self.hits.clear()
