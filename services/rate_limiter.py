import threading
import time


class CooldownRateLimiter:

    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self._expires_at = {}
        self._lock = threading.Lock()

    def acquire(self, key, cooldown_seconds):
        now = self.clock()

        with self._lock:
            expires_at = self._expires_at.get(key, 0.0)
            remaining = expires_at - now

            if remaining > 0:
                return False, remaining

            self._expires_at[key] = (
                now + cooldown_seconds
            )

            if len(self._expires_at) > 1000:
                self._expires_at = {
                    stored_key: expiry
                    for stored_key, expiry
                    in self._expires_at.items()
                    if expiry > now
                }

            return True, 0.0
