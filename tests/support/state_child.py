"""A child process for the lost-run contract test (tests/run/real/test_run_lost.py): it builds the engine of bead t-1 on the worktree and
config dir its environment names, ticks the engine's heartbeat once (the tick the beat thread makes), writes its pid to the marker and
waits to be killed.

    state_child.py marker"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

# isort: split
from support.fakes import FakeBeadStore
from support.spawn import port_git, real_spawner
from support.who import who
from taskloop.app.run import engine
from taskloop.app.wire import slots as wslots
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId


def main(marker: str) -> None:
    eng = engine.Engine(BeadId("t-1"), os.environ["STATE_WT"], wslots.load_cfg(os.environ["STATE_WT"], port_git()),
                        store=FakeBeadStore(), env=snapshot(), spawner=real_spawner(), git=port_git(), who=who())
    eng.log.note("run started")
    eng.records.heartbeat()
    Path(marker + ".tmp").write_text(f"{os.getpid()} {eng.run_id}")
    os.replace(marker + ".tmp", marker)
    time.sleep(120)  # the parent kills this process by its pid


if __name__ == "__main__":
    main(sys.argv[1])
