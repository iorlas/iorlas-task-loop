"""A child process for the kill-and-restart test (tests/run/real/test_close_kill.py): it closes bead t-1 on the worktree and config dir its
environment names, writes every bd write and every close effect it applies to a journal, and (mode `die BEFORE`) parks right before the
effect named BEFORE so the parent can kill it by pid.

    close_child.py die EffectName   journal  marker    close a DONE run; stop before EffectName; write the pid to `marker`
    close_child.py restart          journal             a new process on the same bead: finish what the dead one left"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

# isort: split
from support.fakes import FakeBeadStore
from taskloop.app.run import engine
from taskloop.app.run.closer import Closer
from taskloop.app.wire import slots as wslots
from taskloop.contracts.ids import BeadId
from taskloop.domain import outcome as oc


class Journal(list):
    """bd writes, appended to the journal file the moment they happen (a killed process loses none)."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path

    def append(self, item: object) -> None:
        super().append(item)
        write(self.path, {"bd": list(item)})  # type: ignore[call-overload]


def write(path: str, row: dict) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def main(argv: list[str]) -> None:
    mode, journal = argv[0], argv[-1] if argv[0] == "restart" else argv[2]
    store = FakeBeadStore()
    store.calls = Journal(journal)
    eng = engine.Engine(BeadId("t-1"), os.environ["CLOSE_WT"], wslots.load_cfg(os.environ["CLOSE_WT"]), store=store)
    real = Closer.apply

    def apply(self, eff, *a):
        if mode == "die" and type(eff).__name__ == argv[1]:
            Path(argv[3]).write_text(str(os.getpid()))
            time.sleep(120)  # the parent kills this process by its pid
        write(journal, {"effect": type(eff).__name__})
        real(self, eff, *a)

    Closer.apply = apply  # type: ignore[method-assign]
    if mode == "die":
        eng.checkpoints.save(step="close")  # the record the run's close keeps its outcome and keys in
        eng.leftovers = [{"title": "Leftover one", "why": "later"}]
        eng.closer.close(oc.make(oc.Kind.DONE))
    else:
        write(journal, {"dead": eng.dead is not None, "run": eng.log_path.stem})
        eng.run()


if __name__ == "__main__":
    main(sys.argv[1:])
