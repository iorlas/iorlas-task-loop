"""The verb `tl check [--repo DIR] [--all] [--list] [ID ...]`: the repo's registry of checks (engine.checks of .task-loop.json), run by a
person in the current worktree through the engine's own runner. No ID: the gate's steps (run gate or both), the steps `when` makes due; the
IDs: just those checks, whatever their `run`, always. It claims no bead and writes no bd; of the config folder it writes only the check
cache the engine's checks use."""
import json
from pathlib import Path
from typing import Any

from taskloop.adapters import gitrepo
from taskloop.app.checks.runner import Checker
from taskloop.app.launch.check_host import CliHost
from taskloop.app.wire import slots as wslots
from taskloop.contracts.argv import text_of
from taskloop.contracts.checks import CheckResult
from taskloop.contracts.config import CheckSpec, EngineConfig
from taskloop.domain.checks.specs import gate_items, repo_check

TAIL_LINES = 15


def listing(cfg: EngineConfig) -> list[str]:
    """The registry, one line per check: id, run, group, when, argv."""
    return [f"{k.id}  run={k.run}  group={k.group}  when={','.join(k.when) or '-'}  {text_of(k.argv)}" for k in cfg.checks]


def step_line(c: CheckResult) -> str:
    """One step: its id, what happened (ok, FAILED, cached, skipped and why), the seconds."""
    if c.status == "skipped":
        state = f"skipped ({c.why})"
    elif c.cached:
        state = "cached"
    else:
        state = "ok" if c.exit == 0 else "FAILED"
    return f"{c.id:<24} {state:<30} {round(c.secs):>5}s"


def chosen(cfg: EngineConfig, ids: list[str]) -> list[CheckSpec]:
    """The named checks of the registry, in the order named."""
    known = {k.id: k for k in cfg.checks}
    missing = [i for i in ids if i not in known]
    if missing:
        raise SystemExit(f"tl check: not in the registry: {', '.join(missing)} (tl check --list: {', '.join(known) or 'none'})")
    return [known[i] for i in dict.fromkeys(ids)]


def profile_of(repo: str) -> EngineConfig:
    """The engine block of the worktree's own .task-loop.json (what a person edited, committed or not)."""
    path = Path(repo) / ".task-loop.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"tl check: cannot read {path}: {e}") from None
    return wslots.load_profile(data).engine


def cmd_check(a: Any, host: CliHost | None = None) -> int:
    repo = gitrepo.git("rev-parse", "--show-toplevel", cwd=a.repo) or str(Path(a.repo).resolve())
    cfg = profile_of(repo)
    if a.list:
        print("\n".join(listing(cfg)) or "(no checks in engine.checks)")
        return 0
    items = [repo_check(k, cfg, gate=k.run != "stage") for k in chosen(cfg, a.ids)] if a.ids else gate_items(cfg)
    if not items:
        print("no gate steps: no engine.checks entry says run gate or both")
        return 0
    box = host or CliHost(repo, cfg)
    try:
        run = Checker(box).run_items(items, everything=a.all or bool(a.ids), learn=False)
    finally:
        box.close()
    print("\n".join(step_line(c) for c in run.results))
    reds = [c for c in run.results if c.red]
    for c in reds:
        print(f"\n{c.id} (exit {c.exit}) `{c.cmd}`:")
        print("\n".join(c.tail.strip().splitlines()[-TAIL_LINES:]))
    return 1 if reds else 0
