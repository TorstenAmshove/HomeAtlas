"""#150: `systemPromptOverride` replaces {home_name} (and only that placeholder)."""
import pytest

from app import prompts, tools


@pytest.fixture(autouse=True)
def _db(temp_db):
    return temp_db


def _build(**settings):
    return tools.build_system_prompt(settings)


def test_override_replaces_home_name():
    out = _build(systemPromptOverride="A {home_name} B {home_name}", homeName="Villa")
    assert out.startswith("A Villa B Villa")


def test_override_home_name_fallback():
    assert _build(systemPromptOverride="Hi {home_name}", homeName="").startswith("Hi diesem Haushalt")


def test_override_keeps_other_braces():
    assert _build(systemPromptOverride="x {foo} {} y").startswith("x {foo} {} y")


def test_home_name_with_braces_not_expanded_twice():
    assert _build(systemPromptOverride="{home_name}", homeName="{home_name}").startswith("{home_name}")


def test_blank_override_uses_default():
    out = _build(systemPromptOverride="   ", homeName="Villa")
    assert out.startswith(prompts.CHAT_SYSTEM.format(home_name="Villa"))


def test_state_block_still_appended():
    assert len(_build(systemPromptOverride="x", homeName="V")) > 1
