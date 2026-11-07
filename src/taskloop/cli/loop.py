"""Loop CLI adapters: print app results and install process signal handlers."""

import signal
import threading
from typing import Any

from tlrelease.versions import Installs

from taskloop.app.loop import render
from taskloop.app.loop.env import LoopEnv
from taskloop.app.loop.files import LoopFiles
from taskloop.app.loop.loop import Loop, LoopArgs


def emit(result: tuple[list[str], int]) -> int:
    lines, code = result
    for line in lines:
        print(line)
    return code


def cmd_next(env: LoopEnv, a: Any) -> int:
    return emit(render.cmd_next(env, a.only, a.json))


def cmd_stop(env: LoopEnv, files: LoopFiles, a: Any) -> int:
    return emit(render.cmd_stop(env, files, bool(a.now)))


def cmd_status(env: LoopEnv, files: LoopFiles, installs: Installs, a: Any) -> int:
    return emit(render.cmd_status(env, files, installs, a.last))


def cmd_loop(env: LoopEnv, files: LoopFiles, installs: Installs, a: Any) -> int:
    args = LoopArgs(
        max_beads=a.max_beads,
        until=a.until or "",
        wait_slot_min=a.wait_slot_min,
        wait_drained=a.wait_drained,
        pin=a.pin,
        only=tuple(a.only),
        argv=list(a.argv),
    )
    loop = Loop(env, files, installs, args, env.take_handover())
    main = threading.current_thread() is threading.main_thread()
    old = {sig: signal.signal(sig, lambda *_: loop.sigterm.set()) for sig in (signal.SIGTERM, signal.SIGINT)} if main else {}
    try:
        return loop.main()
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)
