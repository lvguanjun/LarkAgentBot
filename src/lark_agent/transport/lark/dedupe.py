from __future__ import annotations

import time
from collections import OrderedDict


class TTLSeenCache:
    def __init__(self, *, ttl_seconds: float = 600, max_size: int = 4096) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._seen: OrderedDict[str, float] = OrderedDict()

    def seen_or_mark(self, key: str) -> bool:
        now = time.monotonic()
        self._prune(now)
        if key in self._seen:
            self._seen.move_to_end(key)
            return True

        self._seen[key] = now
        while len(self._seen) > self.max_size:
            self._seen.popitem(last=False)
        return False

    def _prune(self, now: float) -> None:
        expired_before = now - self.ttl_seconds
        while self._seen:
            _, created_at = next(iter(self._seen.items()))
            if created_at > expired_before:
                break
            self._seen.popitem(last=False)
