"""The rule runner: rules in order, the first block wins."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# A rule answers one tool call: a Verdict, a reason string (non-empty blocks), or None / "" to allow.
Rule = Callable[[str, Mapping[str, Any]], "Verdict | str | None"]


@dataclass(frozen=True)
class Verdict:
    """The answer to one tool call: blocked with the words the caller reads, or allowed."""

    blocked: bool = False
    reason: str = ""


def judge(rules: Iterable[Rule], tool: str, tool_input: Mapping[str, Any]) -> Verdict:
    """The first rule that blocks `tool` called with `tool_input`; allowed when none does. Exceptions from a rule propagate."""
    for rule in rules:
        answer = rule(tool, tool_input)
        verdict = answer if isinstance(answer, Verdict) else Verdict(blocked=True, reason=answer) if answer else Verdict()
        if verdict.blocked:
            return verdict
    return Verdict()
