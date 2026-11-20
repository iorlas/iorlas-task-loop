"""Which agent harness runs an attempt and which provider answers for its model: the two closed vocabularies, the one place the
provider is derived, and the plain words the dashboard shows.
The harness is a typed per-step machine choice (optionally overridden by `--harness`),
never a constant in the launch."""

from enum import StrEnum


class HarnessKind(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    OPENCODE = "opencode"


class Provider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    KIMI = "kimi"
    XAI = "xai"
    UNKNOWN = "unknown"


HARNESS_WORDS = {HarnessKind.CODEX: "Codex", HarnessKind.CLAUDE: "Claude Code", HarnessKind.OPENCODE: "OpenCode"}
PROVIDER_WORDS = {Provider.OPENAI: "OpenAI", Provider.ANTHROPIC: "Anthropic", Provider.DEEPSEEK: "DeepSeek", Provider.KIMI: "Kimi",
                  Provider.XAI: "xAI", Provider.UNKNOWN: "provider unknown"}
# OpenCode serves many providers: the model id names whose model it is (`opencode/deepseek-v4.1-flash-free`, `moonshotai/kimi-k2`).
_BY_MODEL = (("deepseek", Provider.DEEPSEEK), ("kimi", Provider.KIMI), ("moonshot", Provider.KIMI), ("grok", Provider.XAI),
             ("xai", Provider.XAI), ("gpt", Provider.OPENAI), ("openai", Provider.OPENAI), ("claude", Provider.ANTHROPIC),
             ("anthropic", Provider.ANTHROPIC))


def provider_of(harness: HarnessKind, model: str) -> Provider:
    """The provider whose model runs: fixed for Codex and Claude Code, read from the model id for OpenCode."""
    if harness is HarnessKind.CODEX:
        return Provider.OPENAI
    if harness is HarnessKind.CLAUDE:
        return Provider.ANTHROPIC
    lowered = model.casefold()
    return next((provider for word, provider in _BY_MODEL if word in lowered), Provider.UNKNOWN)
