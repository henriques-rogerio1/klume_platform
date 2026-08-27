import time

from api.rate_limit import RateLimiter


def test_allows_under_limit():
    rl = RateLimiter(max_requests=3, window_seconds=60)
    assert rl.allow("k") and rl.allow("k") and rl.allow("k")


def test_blocks_over_limit():
    rl = RateLimiter(max_requests=2, window_seconds=60)
    assert rl.allow("k") and rl.allow("k")
    assert rl.allow("k") is False


def test_resets_after_window():
    rl = RateLimiter(max_requests=1, window_seconds=0.05)
    assert rl.allow("k") is True
    assert rl.allow("k") is False
    time.sleep(0.06)
    assert rl.allow("k") is True


def test_keys_are_independent():
    rl = RateLimiter(max_requests=1, window_seconds=60)
    assert rl.allow("a") is True
    assert rl.allow("b") is True
    assert rl.allow("a") is False
