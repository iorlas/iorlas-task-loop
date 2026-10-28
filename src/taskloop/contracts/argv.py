"""A check is an argv list. Its one-line text (what logs, caches and prompts show) is shlex.join of the list, and the list comes
back with shlex.split: a pure round trip, no shell semantics anywhere."""
import copy
import shlex
from collections.abc import Sequence
from typing import Any

FORM = ('a check is an argv list of strings, e.g. ["python3", "-m", "unittest"]; a pipeline, redirect or loop goes into a '
        'repo recipe (a just target or a script) that the argv calls, e.g. ["just", "name"]')
OPERATORS = frozenset({"&&", "||", "|", ";", "&", ">", ">>", "<", "<<", "2>&1", "&>", "|&", "(", ")"})
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish"})
SHELL_FLAGS = ("-c", "-lc", "-ic", "-cl")


def text_of(argv: Sequence[str]) -> str:
    """The argv as one line of text."""
    return shlex.join(argv)


def argv_of(text: str) -> list[str]:
    """The argv a one-line text (from text_of) stands for."""
    return shlex.split(text)


def shape_problem(value: object) -> str:
    """Why `value` is not an argv list, '' when it is: a string is the old form and is refused."""
    if isinstance(value, str):
        return f"a string command `{value[:80]}` is not allowed: {FORM}"
    if not isinstance(value, list) or not value or not all(isinstance(x, str) for x in value) or not value[0].strip():
        return f"`{value!r:.80}` is not a non-empty list of strings: {FORM}"
    return ""


def argv_problems(argv: Sequence[str]) -> list[str]:
    """[why] an argv list is a shell string in disguise: an operator word, or a shell run on a command string."""
    out = [f"`{x}` is a literal argument in an argv, not a shell operator: {FORM}" for x in dict.fromkeys(argv) if x in OPERATORS]
    if argv and argv[0].rsplit("/", maxsplit=1)[-1] in SHELLS and any(x in SHELL_FLAGS for x in argv[1:3]):
        out.append(f"a shell run on a command string is a string command again: {FORM}")
    return out


def checks_to_text(plan: dict[str, Any]) -> None:
    """A planner's or writer's answer (every check an argv list) in the text form the engine keeps: a stage's checks, a risk's, a
    case's and a new case's check. An empty list (no command) becomes ''. In place; text stays text."""
    if not isinstance(plan, dict):
        return
    for st in plan.get("stages") or []:
        st["checks"] = [c if isinstance(c, str) else text_of(c) for c in st["checks"]]
    for k in ("risks", "cases", "new_cases"):
        for x in plan.get(k) or []:
            if not isinstance(x.get("check"), str):
                x["check"] = text_of(x["check"]) if x.get("check") else ""


def checks_to_wire(plan: dict[str, Any]) -> dict[str, Any]:
    """A copy of the engine's plan with every check an argv list again, as the planner is shown it and writes it."""
    out = copy.deepcopy(plan)
    for st in out.get("stages") or []:
        st["checks"] = [argv_of(c) if isinstance(c, str) else c for c in st.get("checks") or []]
    for k in ("risks", "cases"):
        for x in out.get(k) or []:
            if isinstance(x.get("check"), str):
                x["check"] = argv_of(x["check"])
    return out
