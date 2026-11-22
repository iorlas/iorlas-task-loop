"""Which reasoning-effort levels a configured model accepts, asked of its harness (local files only; None means it cannot tell)."""

from pathlib import Path

from any_agent import ClaudeHarness, CodexHarness

from taskloop.harness_choice import HarnessKind


def accepted(harness: HarnessKind, model: str, home: Path) -> tuple[str, ...] | None:
    """The levels `model` accepts, or None when unknown (OpenCode cannot say; no environment variable is read, so Codex's
    model list is the one under `home`)."""
    if harness is HarnessKind.CODEX:
        return CodexHarness(env={"CODEX_HOME": str(home / ".codex")}).effort_levels(model)
    if harness is HarnessKind.CLAUDE:
        return ClaudeHarness(env={}).effort_levels(model)
    return None
