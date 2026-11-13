"""The closed harness and provider words and the one place a provider is derived."""

import pytest
from any_agent import CodexHarness

from taskloop.harness_choice import HARNESS_WORDS, PROVIDER_WORDS, HarnessKind, Provider, launchable, provider_of


@pytest.mark.parametrize(("harness", "model", "provider"), [
    (HarnessKind.CODEX, "gpt-5.5", Provider.OPENAI),
    (HarnessKind.CODEX, "anything", Provider.OPENAI),
    (HarnessKind.CLAUDE, "opus", Provider.ANTHROPIC),
    (HarnessKind.OPENCODE, "opencode/deepseek-v4.1-flash-free", Provider.DEEPSEEK),
    (HarnessKind.OPENCODE, "moonshotai/kimi-k2", Provider.KIMI),
    (HarnessKind.OPENCODE, "xai/grok-4", Provider.XAI),
    (HarnessKind.OPENCODE, "openai/gpt-5", Provider.OPENAI),
    (HarnessKind.OPENCODE, "mystery", Provider.UNKNOWN),
])
def test_the_provider_is_derived_from_the_harness_and_for_opencode_the_model_id(
    harness: HarnessKind, model: str, provider: Provider
) -> None:
    assert provider_of(harness, model) is provider


def test_every_word_has_its_plain_name_and_only_codex_is_launchable() -> None:
    assert set(HARNESS_WORDS) == set(HarnessKind) and set(PROVIDER_WORDS) == set(Provider)
    assert isinstance(launchable(HarnessKind.CODEX), CodexHarness)
    assert launchable(HarnessKind.CLAUDE) is None and launchable(HarnessKind.OPENCODE) is None
