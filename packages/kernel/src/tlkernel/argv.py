"""A check is an argv list. Its one-line text (what logs, caches and prompts show) is shlex.join of the list, and the list comes
back with shlex.split: a pure round trip, no shell semantics anywhere."""
import shlex
from collections.abc import Sequence
from typing import Final

FORM: Final = ('a check is an argv list of strings, e.g. ["python3", "-m", "unittest"]; a pipeline, redirect or loop goes into a '
        'repo recipe (a just target or a script) that the argv calls, e.g. ["just", "name"]')
OPERATORS: Final = frozenset({"&&", "||", "|", ";", "&", ">", ">>", "<", "<<", "2>&1", "&>", "|&", "(", ")"})
SHELLS: Final = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish"})
SHELL_FLAGS: Final = ("-c", "-lc", "-ic", "-cl")


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
