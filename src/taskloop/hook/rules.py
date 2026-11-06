"""What a PreToolUse hook refuses, one pure function per rule: tool name and input in, a one-line reason out ("" = allowed)."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from any_shell_policy import judge, parse

KILLERS = frozenset({"pkill", "killall"})


def kills_by_name(command: str) -> bool:
    """A pkill or killall in command position of `command`, also behind wrappers and inside `sh -c '...'`. A command that does not
    parse is allowed (the shell will refuse it), never guessed at."""
    return any(c.name in KILLERS for c in parse(command) or ())


def no_kill_by_name(tool: str, args: Mapping[str, Any]) -> str:
    if tool == "Bash" and kills_by_name(str(args.get("command") or "")):
        return "pkill and killall kill by name or pattern, other sessions' processes included: kill the PID you started."
    return ""


RULES = (no_kill_by_name,)


def deny_reason(tool: str, args: Mapping[str, Any]) -> str:
    return judge(RULES, tool, args).reason
