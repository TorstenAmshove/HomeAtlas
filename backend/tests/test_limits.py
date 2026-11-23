import pytest

from app.limits import SlidingWindowLimiter


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_limits_and_release():
    c = Clock()
    lim = SlidingWindowLimiter(2, 60, clock=c)
    assert lim.allow("a") == (True, 0)
    assert lim.allow("a") == (True, 0)
    ok, retry = lim.allow("a")
    assert not ok and retry == 60
    c.t += 30.2
    ok, retry = lim.allow("a")
    assert not ok and retry == 30  # ceil(29.8)
    c.t += 29.8
    assert lim.allow("a")[0]


def test_keys_independent_and_rejected_not_counted():
    c = Clock()
    lim = SlidingWindowLimiter(1, 10, clock=c)
    assert lim.allow("a")[0]
    assert lim.allow("b")[0]
    for _ in range(5):
        assert not lim.allow("a")[0]
    c.t += 10
    assert lim.allow("a")[0]


def test_empty_keys_cleaned_up():
    c = Clock()
    lim = SlidingWindowLimiter(1, 10, clock=c)
    lim.allow("a")
    c.t += 11
    lim.allow("b")
    assert "a" not in lim._hits


def test_invalid_args():
    with pytest.raises(ValueError):
        SlidingWindowLimiter(0, 10)
    with pytest.raises(ValueError):
        SlidingWindowLimiter(1, 0)
