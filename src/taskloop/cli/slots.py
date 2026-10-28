"""`tl slot VERB`: one table from verb to function. Parsing is tl.py's; building the env is tl.py's; this only picks."""
from collections.abc import Callable
from typing import Any, Final

from taskloop.app.slots.env import SlotEnv
from taskloop.app.slots.verbs import hold, init, listing, release, reset, run_setup, take

VERBS: Final[dict[str, Callable[[SlotEnv, Any], int]]] = {
    "list": listing, "hold": hold, "init": init, "take": take, "release": release, "reset": reset, "setup": run_setup,
}


def run(env: SlotEnv, a: Any) -> int:
    verb = VERBS.get(a.op)
    return verb(env, a) if verb else 2
