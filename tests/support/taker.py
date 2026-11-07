"""A Taker over the real slot and park adapters (app/loop/takeports.py), for the tests that drive the slots themselves."""
from collections.abc import Callable

import support.paths  # noqa: F401
from taskloop.app.loop import verdict as vd
from taskloop.app.loop.env import LoopEnv
from taskloop.app.loop.run import BeadRun
from taskloop.app.loop.take import Taker
from taskloop.app.loop.takeports import EngineSlots, ParkGate
from taskloop.contracts.config import LoopConfig


def real_taker(env: LoopEnv, run: BeadRun, tune: Callable[[], LoopConfig], say: Callable[[str], None],
               record: Callable[[str, str, vd.Verdict], None], later: dict[str, float]) -> Taker:
    return Taker(env, run, tune, say, record, later, EngineSlots(env), ParkGate(env))
