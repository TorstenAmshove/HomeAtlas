import pytest

from app import security


def test_trims_and_keeps_case():
    assert security.normalize_username("  Anna.B@Home  ") == "Anna.B@Home"


def test_unicode_letters_allowed():
    assert security.normalize_username("Jörg_Müller-1") == "Jörg_Müller-1"


@pytest.mark.parametrize("bad", ["", "   ", "a b", "a\tb", "a​b", "a\x00b", "a/b", "a" * 65])
def test_rejects(bad):
    with pytest.raises(security.UsernameError):
        security.normalize_username(bad)


def test_length_limit_boundary():
    assert security.normalize_username("a" * 64) == "a" * 64
