#!/usr/bin/env python3
"""Real kill -9 at every point of the close's effects: the crash matrix with a process that dies, not a fake.

    uv run python dev/killpoints.py [--only I:PHASE] [--keep]

For each effect I of a landed run's close plan (the land's two effects first) and each PHASE (`before` the effect, `after_effect` it
ran and its key is not written, `after_mark` its key is written) a child process runs the real interpreter over a real checkpoint row
in a scratch config dir and kills itself with SIGKILL there. A second child then resumes from what the first left. The effects leave
a line each in a world file, outside the process. The rule: every effect is in the world file; the order of first appearances is the
plan's; an effect is there twice only when it was killed in `after_effect` (the at-least-once the interpreter documents), and none
other; a resume of a closed run (its last effect dropped the checkpoint) does nothing. Exit 1 on the first broken rule.
Not wired to a scheduler: a nightly job is the owner's to set up (tl-7i9k.13)."""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASES = ("before", "after_effect", "after_mark")
BEAD, RUN = "t-1", "r1"


def child(config: str, kill: str, seed: bool) -> int:
    """The process that dies: the real interpreter and checkpoint ledger, a world file for the effects."""
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "skills" / "task-loop" / "_vendor")]
    from taskloop.contracts.checkpoint import Checkpoint  # noqa: PLC0415
    from taskloop.contracts.kinds import Kind  # noqa: PLC0415
    from taskloop.contracts.paths import ConfigDir  # noqa: PLC0415
    from taskloop.domain import effects as fx  # noqa: PLC0415
    from taskloop.domain import outcome as oc  # noqa: PLC0415
    from taskloop.domain.interpret import CheckpointLedger, interpret  # noqa: PLC0415
    from taskloop.stores.real import real_stores  # noqa: PLC0415

    at, _, phase = kill.partition(":")
    doc = real_stores(ConfigDir(config)).checkpoints.of(BEAD)
    if seed:
        doc.write(Checkpoint(bead=BEAD, run=RUN, t=1.0, step="close"))
    if doc.get() is None:
        return 0  # the close finished and dropped its record: nothing to resume
    plan: list[fx.Effect] = [*fx.plan_land("abc"), *fx.plan_close(oc.make(Kind.LANDED, "landed", sha="abc"), dry=False,
                                                                 branch="task/t-1", slot_gen=2)]
    world = Path(config) / "world.log"
    here = [-1]  # the plan index of the effect in hand

    def die(where: str) -> None:
        if kill and where == phase and here[0] == int(at):
            os.kill(os.getpid(), signal.SIGKILL)

    class Keys:
        def applied(self) -> frozenset[str]:
            ck = doc.get()
            return frozenset(ck.applied if ck else ())

        def mark_applied(self, key: str) -> None:
            doc.modify(lambda ck: ck.replace(applied=[*ck.applied, key]) if key not in ck.applied else ck)  # no record, no key
            die("after_mark")

    def apply(eff: fx.Effect) -> None:
        here[0] = plan.index(eff)
        die("before")
        with world.open("a", encoding="utf-8") as out:
            out.write(fx.name_of(eff) + "\n")
            out.flush()
            os.fsync(out.fileno())
        if isinstance(eff, fx.DropCheckpoint):
            doc.delete()
        die("after_effect")

    interpret(BEAD, RUN, plan, CheckpointLedger(Keys()), apply)
    return 0


def plan_names() -> list[str]:
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "skills" / "task-loop" / "_vendor")]
    from taskloop.contracts.kinds import Kind  # noqa: PLC0415
    from taskloop.domain import effects as fx  # noqa: PLC0415
    from taskloop.domain import outcome as oc  # noqa: PLC0415

    plan = [*fx.plan_land("abc"), *fx.plan_close(oc.make(Kind.LANDED, "landed", sha="abc"), dry=False, branch="task/t-1", slot_gen=2)]
    return [fx.name_of(e) for e in plan]


def run_child(config: str, kill: str, seed: bool) -> int:
    argv = [sys.executable, str(Path(__file__).resolve()), "--child", config, "--kill", kill] + (["--seed"] if seed else [])
    return subprocess.run(argv, check=False, capture_output=True, text=True, timeout=120).returncode


def verdict(names: list[str], world: list[str], at: int, phase: str) -> str:
    """"" when the world file holds what the rule says, else what is wrong."""
    seen = Counter(world)
    missing = [n for n in names if not seen[n]]
    if missing:
        return f"never applied: {', '.join(missing)}"
    if list(dict.fromkeys(world)) != names:
        return f"order of first appearances is {list(dict.fromkeys(world))}, the plan's is {names}"
    twice = {n for n, c in seen.items() if c > 1}
    allowed = {names[at]} if phase == "after_effect" and names[at] != "drop_checkpoint" else set()
    if twice != allowed or any(c > 2 for c in seen.values()):
        return f"applied more than once: {sorted(twice)} (allowed: {sorted(allowed)})"
    return ""


def one(names: list[str], at: int, phase: str, keep: bool) -> str:
    config = tempfile.mkdtemp(prefix="killpoints-")
    try:
        first = run_child(config, f"{at}:{phase}", seed=True)
        if first != -signal.SIGKILL:
            return f"the child was not killed (exit {first})"
        if run_child(config, "", seed=False):
            return "the resume failed"
        log = Path(config) / "world.log"
        return verdict(names, log.read_text(encoding="utf-8").split() if log.is_file() else [], at, phase)
    finally:
        if not keep:
            shutil.rmtree(config, ignore_errors=True)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", default="", help="I:PHASE, one kill point")
    ap.add_argument("--keep", action="store_true", help="keep the scratch config dirs")
    ap.add_argument("--child", default="")
    ap.add_argument("--kill", default="")
    ap.add_argument("--seed", action="store_true")
    a = ap.parse_args(argv)
    if a.child:
        return child(a.child, a.kill, a.seed)
    names = plan_names()
    points = [(int(a.only.split(":")[0]), a.only.split(":")[1])] if a.only else [(i, p) for i in range(len(names)) for p in PHASES]
    broken = 0
    for at, phase in points:
        why = one(names, at, phase, a.keep)
        broken += bool(why)
        print(f"{'FAIL' if why else 'ok  '} kill {phase:12} at {names[at]:16} {why}")
    print(f"{len(points) - broken} of {len(points)} kill points hold")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
