"""`tl selftest`: one bead through Engine.run (plan, write, review, land) with a scripted lane in a temp repo and a temp config
dir, on this install's code. A newer install must pass it before a loop moves to it."""
import json
import os
import shlex
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Final
from unittest import mock

from taskloop.adapters import delegate as dg
from taskloop.adapters import ident
from taskloop.adapters.runner import Completed, Seam, completed
from taskloop.app.launch.selftest_beads import MemoryBeads
from taskloop.app.release import seams
from taskloop.app.run.engine import Engine
from taskloop.app.wire import real
from taskloop.app.wire import slots as wslots
from taskloop.contracts import env as penv
from taskloop.contracts.bead import Bead
from taskloop.contracts.env import Env
from taskloop.contracts.ids import parse_bead_id
from taskloop.contracts.ports import Git
from taskloop.contracts.slots import SlotGitError

# an argv list; the plan schema wraps it as an adhoc check
CHECK: Final = ["test", "-f", "f.txt"]
PLAN: Final[dict[str, Any]] = {"summary": "do it",
        "stages": [{"goal": "add f", "files": ["f.txt"], "checks": [{"kind": "adhoc", "argv": CHECK, "reads": []}], "hard": False}],
        "risks": [], "question": "", "options": [], "decided": "", "cases": [], "leftovers": []}
WRITE: Final[dict[str, Any]] = {"summary": "wrote f", "checks_run": [{"cmd": shlex.join(CHECK), "exit": 0}], "question": "", "options": [],
         "decided": "",
         "bad_checks": [], "new_cases": [], "unchecked": [], "logic_only": ""}
REVIEW: Final[dict[str, Any]] = {
    "findings": [],
    "unmet": [],
    "criteria": [],
    "question": "",
    "options": [],
    "decided": "",
    "leftovers": [],
    "unchecked": [],
    "look": "",
}


def lane(cmd: list[str], **kw: Any) -> Completed:
    """Fake route.py run: one contract 3 answer on stdout."""
    schema = json.loads(Path(cmd[cmd.index("--schema") + 1]).read_text(encoding="utf-8"))
    props, cwd = schema.get("properties", {}), cmd[cmd.index("--cwd") + 1]
    if "stages" in props:
        data, node = PLAN, "plan"
    elif "checks_run" in props:
        data, node = WRITE, "write"
        Path(cwd, "f.txt").write_text("f\n", encoding="utf-8")
    else:
        brief = Path(cmd[cmd.index("--brief") + 1]).read_text(encoding="utf-8")
        ids = [ln.split(". ", 1)[0] for ln in brief.splitlines() if ln[:1] == "A" and ln.split(". ", 1)[0][1:].isdigit()]
        data, node = dict(REVIEW, criteria=[{"item": i, "status": "met", "evidence": "the checks pass"} for i in ids]), "review"
    tokens = {"in": 1, "cached": 0, "out": 1}
    j: dict[str, Any] = {"contract": dg.CONTRACT, "data": data, "text": "ok", "say": "", "ref": "ref-" + node, "lane": "L", "model": "m",
         "effort": "e",
         "family": "openai" if node == "write" else "claude", "flag": None, "fallback": False, "first_lane": "L", "rung": 0,
         "tokens": tokens, "cost": 0.0, "secs": 1, "run_id": "selftest", "call_id": "selftest", "denied": [], "git_violation": [],
         "warnings": [], "usage": {"tokens": tokens, "cost": 0.0, "secs": 1, "turns": 1, "ref": "ref-" + node}, "stop": None,
         "resumed": False}
    return completed(cmd, 0, json.dumps(j))


class Runner(Seam):
    """The engine's process seam for the fake lane."""

    def __call__(self, cmd: list[str], **kw: Any) -> Completed:
        self.stop = {}
        self.obs = {}
        return lane(cmd, **kw)


def git_repo(home: Path, wt: Path, git: Git) -> str | None:
    """A bare origin and a clone of it with one commit on main; None, or what git said."""
    try:
        git.init_bare(str(home / "o.git"), "main")
        git.clone(str(home / "o.git"), str(wt))
        (wt / "a.txt").write_text("a\n", encoding="utf-8")
        git.commit_all(str(wt), "main", "init")
        git.push(str(wt), "origin", "HEAD:main")
    except SlotGitError as e:
        return f"git: {e}"
    return None


def run_engine(home: Path, wt: Path, env: Env) -> tuple[int, Bead]:
    """(exit code, the bead as the fake bd holds it) after one bead ran through the engine on the scripted lane."""
    cfg = wslots.load_cfg(str(wt), real.git(env))
    res = seams.resolve_delegate(cfg.delegate)  # the configured delegate's own contract when there is one; else a bare one
    contract = res.contract if isinstance(res, dg.Resolved) else {"contract": dg.CONTRACT, "reasons": {}, "run_args": []}
    resolved = dg.Resolved(Path("/selftest"), "/selftest/route.py", contract, "explicit")
    store = MemoryBeads()
    t1 = parse_bead_id("t-1")
    store.beads[t1] = Bead(id=t1, title="Add f", status="open", acceptance_criteria="f.txt exists")
    cfg = cfg.replace(reflect=False)
    os.chdir(wt)  # the engine reads cwd
    try:
        with mock.patch.object(time, "sleep"):
            rc = Engine(
                t1,
                str(wt),
                cfg,
                route=seams.FixedRoute(resolved, Runner()),
                store=store,
                env=env,
                spawner=real.spawner(env),
                git=real.git(env),
                who=ident.identity(env),
            ).run()
    finally:
        os.chdir(home.parent)  # out of the directory that is removed next
    return rc, store.beads[t1]


def selftest(process: Env):
    """None when one bead lands and closes, else why not. Nothing real is touched: no bd, no delegate, no network, no model."""
    with tempfile.TemporaryDirectory(prefix="tl-selftest-") as tmp:
        home = Path(os.path.realpath(tmp))
        env = {
            "XDG_CONFIG_HOME": str(home / "cfg"),
            "APPDATA": str(home / "cfg"),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "CLAUDE_CODE_SESSION_ID": "selftest-0",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        engine_env = Env({**process.vars, **env})
        with penv.patched(env):
            why = git_repo(home, home / "wt", real.git(engine_env))
            if why:
                return why
            rc, bead = run_engine(home, home / "wt", engine_env)
    if rc != 0 or bead.status != "closed":
        return f"the engine ended {rc} with the bead {bead.status} instead of closed"
    return None


def cmd_selftest(a: Any, *, env: Env) -> int:
    started = time.monotonic()
    try:
        why = selftest(env)
    except Exception as e:  # any raise is a failure; the traceback tail says where
        why = "{}: {}\n{}".format(type(e).__name__, e, "".join(traceback.format_exc().splitlines(True)[-6:]))
    secs = time.monotonic() - started
    if why:
        print(f"selftest FAILED in {secs:.1f} s: {why}", file=sys.stderr)
        return 1
    print(f"selftest ok in {secs:.1f} s")
    return 0
