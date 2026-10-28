"""The absent-loop verdict: ready beads, no live loop and no beat for `absent` seconds."""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LoopHealth:
    alive: int
    ready: int
    last_beat: float
    verdict: Literal["ok", "idle_ok", "absent"]


def loop_health(alive: int, ready: int, last_beat: float, now: float, absent: float = 600) -> LoopHealth:
    """absent iff ready beads, no live loop and no beat for `absent` seconds; idle_ok: nothing ready."""
    if alive:
        verdict: Literal["ok", "idle_ok", "absent"] = "ok"
    elif ready > 0 and (not last_beat or now - last_beat > absent):
        verdict = "absent"
    else:
        verdict = "idle_ok"
    return LoopHealth(alive, ready, last_beat or 0.0, verdict)
