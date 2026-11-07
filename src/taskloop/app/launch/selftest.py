"""Bind the isolated selftest scenario to the installed engine and real adapters."""
import os
from pathlib import Path
from typing import Any

from tlkernel.bead import Bead
from tlkernel.delegateport import Resolved
from tlkernel.env import Env
from tlkernel.ids import parse_bead_id
from tlkernel.memory_beads import MemoryBeads
from tlslots import config as wslots_config

from taskloop.adapters import ident
from taskloop.app.doctor import selftest
from taskloop.app.run.engine import Engine
from taskloop.app.wire import real
from taskloop.stores.delegate import fixed_route, real_route


def run_engine(home: Path, wt: Path, env: Env) -> tuple[int, Bead]:
    """(exit code, the bead as the fake bd holds it) after one bead ran through the engine on the scripted lane."""
    cfg = wslots_config.load_cfg(str(wt), real.git(env))
    found = real_route().resolve()
    resolved = Resolved(Path("/selftest"), "/selftest/route.py", found.contract if isinstance(found, Resolved) else {}, "explicit")
    store = MemoryBeads()
    t1 = parse_bead_id("t-1")
    store.beads[t1] = Bead(id=t1, title="Add f", status="open", acceptance_criteria="f.txt exists")
    cfg = cfg.replace(reflect=False)
    os.chdir(wt)  # the engine reads cwd
    try:
        rc = Engine(
            t1,
            str(wt),
            cfg,
            route=fixed_route(resolved, selftest.Runner(real_route().contract_no)),
            store=store,
            env=env,
            spawner=real.spawner(env),
            git=real.git(env),
            who=ident.identity(env),
        ).run()
    finally:
        os.chdir(home.parent)  # out of the directory that is removed next
    return rc, store.beads[t1]


def cmd_selftest(a: Any, *, env: Env) -> int:
    return selftest.report(lambda: selftest.selftest(env, run_engine, real.git, Env))
