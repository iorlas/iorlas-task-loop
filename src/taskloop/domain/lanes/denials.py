"""Which refusals a retry may answer. A guard that blocks a write for `secrets` because a heredoc body mentions `.env` has
made a mistake worth one retry (tell the worker to use apply_patch); a guard that names a real secret path has not."""

from collections.abc import Sequence
from typing import Final

from taskloop.contracts.delegate import Denial

READ_TOOLS: Final = ("Bash", "shell", "bash")


def command_of(d: Denial) -> str:
    """The command a refusal names: the tool's input is an object."""
    inp = d.input
    return str(inp.get("command") or inp.get("cmd") or inp or d.tool or "")


def heredoc_body_names_env(cmd: str) -> bool:
    """`.env` appears in the text of a heredoc body and nowhere in the command line that opens it."""
    head, sep, body = cmd.partition("\n")
    if "<<" not in head or not sep:
        return False
    return ".env" in body and ".env" not in head


def secret_false_positive(denied: Sequence[Denial]) -> bool:
    """Every real denial is kind `secret`, names no path, and is a heredoc whose body (not its command line) holds `.env`."""
    real = [d for d in denied if d.kind != "sandbox_limit"]
    return bool(real) and all(d.kind == "secret" and not d.path and heredoc_body_names_env(command_of(d)) for d in real)
