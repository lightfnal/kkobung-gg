import unittest

from services.rate_limiter import CooldownRateLimiter


class FakeClock:

    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class TestCooldownRateLimiter(unittest.TestCase):

    def test_same_key_is_blocked_until_cooldown_expires(self):
        clock = FakeClock()
        limiter = CooldownRateLimiter(clock=clock)

        first_allowed, _ = limiter.acquire("command", 2)
        second_allowed, remaining = limiter.acquire("command", 2)

        self.assertTrue(first_allowed)
        self.assertFalse(second_allowed)
        self.assertEqual(remaining, 2)

        clock.advance(2)
        third_allowed, remaining = limiter.acquire("command", 2)

        self.assertTrue(third_allowed)
        self.assertEqual(remaining, 0)

    def test_different_users_and_commands_do_not_block_each_other(self):
        limiter = CooldownRateLimiter(clock=FakeClock())

        self.assertTrue(limiter.acquire(("user-1", "참가"), 2)[0])
        self.assertTrue(limiter.acquire(("user-2", "참가"), 2)[0])
        self.assertTrue(limiter.acquire(("user-1", "명단"), 2)[0])
