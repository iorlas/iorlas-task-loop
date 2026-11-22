"""Which reasoning-effort levels a configured model accepts, asked of its harness (local files only; None means it cannot tell)."""

from pathlib import Path

from any_agent import ClaudeHarness, CodexHarness

from taskloop.harness_choice import HarnessKind


class EffortRefused(ValueError):
    """An effort level the chosen harness and model do not accept."""


def accepted(harness: HarnessKind, model: str, home: Path) -> tuple[str, ...] | None:
    """The levels `model` accepts, or None when unknown (OpenCode cannot say; no environment variable is read, so Codex's
    model list is the one under `home`)."""
    if harness is HarnessKind.CODEX:
        return CodexHarness(env={"CODEX_HOME": str(home / ".codex")}).effort_levels(model)
    if harness is HarnessKind.CLAUDE:
        return ClaudeHarness(env={}).effort_levels(model)
    return None


def require(effort: str, harness: HarnessKind, model: str, home: Path) -> None:
    """Refuse an effort level that is known not to be accepted; unknown levels pass."""
    levels = accepted(harness, model, home)
    if levels is not None and effort not in levels:
        raise EffortRefused(f"effort {effort!r} is not accepted by {harness.value} model {model!r}; it accepts {', '.join(levels)}")
