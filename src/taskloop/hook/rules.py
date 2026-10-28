"""What a PreToolUse hook refuses, one pure function per rule: tool name and input in, a one-line reason out ("" = allowed)."""
import os
import shlex
from collections.abc import Mapping
from typing import Any

KILLERS = frozenset({"pkill", "killall"})
SHELLS = frozenset({"sh", "bash", "zsh", "dash"})
WRAPPERS = frozenset({"sudo", "exec", "env", "nohup", "time", "command", "xargs", "nice"})
BREAKS = frozenset({";", "&", "|", "&&", "||", "(", ")"})


def words(command: str) -> list[str]:
    lex = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    return list(lex)


def kills_by_name(command: str, depth: int = 0) -> bool:
    """A pkill or killall in command position of `command`, also inside `sh -c '...'`. A command that does not parse is allowed
    (the shell will refuse it), never guessed at."""
    try:
        toks = words(command)
    except ValueError:
        return False
    at_start = True
    for i, tok in enumerate(toks):
        if tok in BREAKS:
            at_start = True
            continue
        name = os.path.basename(tok)
        if at_start and name in KILLERS:
            return True
        if at_start and name in SHELLS and depth < 3 and "-c" in toks[i + 1:i + 3]:
            j = toks.index("-c", i) + 1
            if j < len(toks) and kills_by_name(toks[j], depth + 1):
                return True
        at_start = at_start and name in WRAPPERS
    return False


def no_kill_by_name(tool: str, args: Mapping[str, Any]) -> str:
    if tool == "Bash" and kills_by_name(str(args.get("command") or "")):
        return "pkill and killall kill by name or pattern, other sessions' processes included: kill the PID you started."
    return ""


RULES = (no_kill_by_name,)


def deny_reason(tool: str, args: Mapping[str, Any]) -> str:
    for rule in RULES:
        why = rule(tool, args)
        if why:
            return why
    return ""
