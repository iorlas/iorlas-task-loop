"""CheckLog: the records of the checks of a round. Every check leaves a start and an end under one id (one that never ran, a
cached or reused or skipped result, leaves both at once), and the round leaves one Checks record: the CheckRun."""
import argparse
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from tlkernel import inputsets
from tlkernel.argv import text_of
from tlkernel.checks import Check, CheckResult, CheckRun, Phase
from tlkernel.config import CheckSpec, EngineConfig
from tlkernel.ids import CheckId
from tlkernel.log import CheckEnd, Checks, CheckStart

from taskloop.app.checks.host import CheckHost
from taskloop.domain.checks.specs import gate_items, repo_check
from taskloop.stores.runlog import RunLog


class CheckLog:
    def __init__(self, log: RunLog) -> None:
        self.log = log
        self.env: dict[str, str] = {}
        self.logged: set[CheckId] = set()

    def start(self, c: Check, rnd: int, log: str = "") -> str:
        """A check begins running: its id, which `close` ends."""
        cid = self.log.next_id("k")
        self.log.emit(CheckStart(id=cid, check=c.id, group=c.group, cmd=c.cmd, round=rnd, log=log, timeout_s=c.wall_min * 60,
                               lane=c.lane))
        if c.run_in == "slot":
            self.log.note(f"check {c.id}: execution in slot")
        return cid

    def close(self, c: Check, res: CheckResult, cid: str | None, rnd: int) -> None:
        """The check's result; `cid` None: it did not run (skipped, cached, reused), so its start is written now."""
        cid = cid or self.start(c, rnd, res.log)
        self.log.emit(CheckEnd(id=cid, exit=res.exit, status=res.word, tries=res.tries, exec_seconds=res.secs, wall_hit=res.wall_hit,
                               wait_seconds=res.waited, lane=c.lane, at=res.at, cancelled=res.cancelled))

    def round(self, node_id: str, run: CheckRun) -> None:
        self.log.emit(Checks(node_id=node_id, run=run))


TAIL_LINES = 15


def listing(cfg: EngineConfig) -> list[str]:
    """The registry, one line per check: id, run, group, when, argv."""
    return [f"{k.id}  run={k.run}  group={k.group}  when={','.join(inputsets.expand(cfg, k.when)) or '-'}  {text_of(k.argv)}"
            for k in cfg.checks]


def step_line(c: CheckResult) -> str:
    """One step: its id, what happened (ok, FAILED, cached, skipped and why), the seconds."""
    if c.status == "skipped":
        state = f"skipped ({c.why})"
    elif c.status == "unverified":
        state = "UNVERIFIED"
    elif c.cached:
        state = "cached"
    else:
        state = "ok" if c.exit == 0 else "FAILED"
    return f"{c.id:<24} {state:<30} {round(c.secs):>5}s"



def render(run: CheckRun, run_dir: Path) -> int:
    """Print the standalone result and failure evidence, returning its exit status."""
    print("\n".join(step_line(c) for c in run.results))
    reds = [c for c in run.results if c.red]
    if reds:
        print(f"evidence kept in {run_dir}")
    for c in reds:
        print(f"\n{c.id} (exit {c.exit}) `{c.cmd}`:")
        print("\n".join(c.tail.strip().splitlines()[-TAIL_LINES:]))
    return 1 if reds else 0


class StandaloneChecker(Protocol):
    """The runner operation used by a standalone check."""

    def run_items(self, items: list[Check], *, everything: bool, learn: bool,
                  show_clean: bool, all_files: bool) -> CheckRun: ...


def chosen(cfg: EngineConfig, ids: list[str]) -> list[CheckSpec]:
    """The named checks of the registry, in the order named."""
    known = {str(k.id): k for k in cfg.checks}
    missing = [i for i in ids if i not in known]
    if missing:
        raise SystemExit(f"tl check: not in the registry: {', '.join(missing)} (tl check --list: {', '.join(known) or 'none'})")
    return [known[i] for i in dict.fromkeys(ids)]



def standalone(a: argparse.Namespace, *, profile: Callable[[], EngineConfig],
               workspace: Callable[[EngineConfig, bool], AbstractContextManager[CheckHost]],
               save: Callable[[CheckRun], None], checker: Callable[[CheckHost], StandaloneChecker]) -> int:
    """Select and run a person's checks, keeping the checkout lifetime around execution only."""
    cfg = profile()
    commit = getattr(a, "base_commit", None)
    cfg = cfg.replace(base=commit) if commit else cfg
    if a.list:
        print("\n".join(listing(cfg)) or "(no checks in engine.checks)")
        return 0
    items = [repo_check(k, cfg, Phase.STAGE if k.run == "stage" else Phase.GATE) for k in chosen(cfg, a.ids)] if a.ids else gate_items(cfg)
    if not items:
        print("no gate steps: no engine.checks entry says run gate or both")
    if a.staged and a.all:
        raise SystemExit("tl check: --staged and --all name two different sets of files; pick one")
    with workspace(cfg, a.staged) as box:
        try:
            run = checker(box).run_items(items, everything=a.all or bool(a.ids), learn=False, show_clean=True, all_files=a.all)
        except BaseException:
            print(f"tl check: evidence kept in {box.run_dir}")
            raise
    save(run)
    box.checklog.round("", run)
    return render(run, box.run_dir)
