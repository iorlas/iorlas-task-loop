"""`tl selftest`: one bead through Engine.run (plan, write, review, land) with a scripted lane in a temp repo and a temp config
dir, on this install's code. A newer install must pass it before a loop moves to it."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import engine
import seams
import tl
from taskloop.adapters import delegate as dg
from taskloop.adapters.fake_beads import FakeBeads
from taskloop.adapters.runner import Seam

CHECK = [sys.executable, "-c", "import os,sys; sys.exit(0 if os.path.exists('f.txt') else 1)"]  # an argv list, as the plan schema wants
PLAN = {"summary": "do it", "stages": [{"goal": "add f", "files": ["f.txt"], "checks": [CHECK], "hard": False}],
        "risks": [], "question": "", "options": [], "decided": "", "cases": [], "leftovers": []}
WRITE = {"summary": "wrote f", "checks_run": [{"cmd": shlex.join(CHECK), "exit": 0}], "question": "", "options": [], "decided": "",
         "bad_checks": [], "new_cases": [], "unchecked": [], "logic_only": ""}
REVIEW = {"findings": [], "unmet": [], "criteria": [], "question": "", "options": [], "decided": "", "leftovers": [], "unchecked": [], "look": ""}


def lane(cmd, **kw):
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
    j = {"contract": dg.CONTRACT, "data": data, "text": "ok", "say": "", "ref": "ref-" + node, "lane": "L", "model": "m", "effort": "e",
         "family": "openai" if node == "write" else "claude", "flag": None, "fallback": False, "first_lane": "L", "rung": 0,
         "tokens": tokens, "cost": 0.0, "secs": 1, "run_id": "selftest", "call_id": "selftest", "denied": [], "git_violation": [],
         "warnings": [], "usage": {"tokens": tokens, "cost": 0.0, "secs": 1, "turns": 1, "ref": "ref-" + node}, "stop": None,
         "resumed": False}
    return subprocess.CompletedProcess(cmd, 0, json.dumps(j), "")


class Runner(Seam):
    """The engine's process seam for the fake lane."""

    def __call__(self, cmd, **kw):
        self.stop, self.obs = {}, {}
        return lane(cmd, **kw)


def git_repo(home, wt):
    """A bare origin and a clone of it with one commit on main; None, or what git said."""
    steps = [(home, ["init", "-q", "--bare", "-b", "main", str(home / "o.git")]), (home, ["clone", "-q", str(home / "o.git"), str(wt)])]
    for cwd, cmd in steps:
        r = subprocess.run(["git"] + cmd, cwd=cwd, capture_output=True, text=True, check=False)
        if r.returncode:
            return "git %s: %s" % (cmd[0], r.stderr.strip()[-200:])
    (wt / "a.txt").write_text("a\n", encoding="utf-8")
    for cmd in (["add", "-A"], ["commit", "-qm", "init"], ["push", "-q", "origin", "HEAD:main"]):
        r = subprocess.run(["git"] + cmd, cwd=wt, capture_output=True, text=True, check=False)
        if r.returncode:
            return "git %s: %s" % (cmd[0], r.stderr.strip()[-200:])
    return None


def run_engine(home, wt):
    """(exit code, closes, blocks) of one bead run through the engine on the scripted lane."""
    cfg = engine.load_cfg(str(wt))
    res = seams.resolve_delegate(cfg.delegate)  # the configured delegate's own contract when there is one; else a bare one
    contract = res.contract if isinstance(res, dg.Resolved) else {"contract": dg.CONTRACT, "reasons": {}, "run_args": []}
    resolved = dg.Resolved(Path("/selftest"), "/selftest/route.py", contract, "explicit")
    store, closed, blocked = FakeBeads(), [], []
    store.beads["t-1"] = engine.Bead(id="t-1", title="Add f", status="open", acceptance_criteria="f.txt exists")
    with mock.patch.object(tl, "cmd_close", side_effect=lambda a: closed.append(a.reason) or 0), \
            mock.patch.object(tl, "cmd_block", side_effect=lambda a: blocked.append(a.why) or 0), \
            mock.patch.object(tl, "cmd_land", return_value=0), mock.patch.object(engine.time, "sleep"):
        cfg = engine.dataclasses.replace(cfg, reflect=False)
        os.chdir(wt)  # the engine reads cwd
        try:
            rc = engine.Engine("t-1", str(wt), cfg, route=seams.FixedRoute(resolved, Runner()), store=store).run()
        finally:
            os.chdir(home.parent)  # out of the directory that is removed next
    return rc, closed, blocked


def selftest():
    """None when one bead lands and closes, else why not. Nothing real is touched: no bd, no delegate, no network, no model."""
    with tempfile.TemporaryDirectory(prefix="tl-selftest-") as tmp:
        home = Path(os.path.realpath(tmp))
        env = {"XDG_CONFIG_HOME": str(home / "cfg"), "APPDATA": str(home / "cfg"), "HOME": str(home), "USERPROFILE": str(home),
               "CLAUDE_CODE_SESSION_ID": "selftest-0", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        with mock.patch.dict(os.environ, env):
            why = git_repo(home, home / "wt")
            if why:
                return why
            rc, closed, blocked = run_engine(home, home / "wt")
    if rc != 0 or not closed:
        return "the engine ended %s without closing the bead%s" % (rc, (" (blocked: %s)" % blocked[0][:200]) if blocked else "")
    return None


def cmd_selftest(a):
    started = time.monotonic()
    try:
        why = selftest()
    except Exception as e:  # any raise is a failure; the traceback tail says where
        import traceback
        why = "%s: %s\n%s" % (type(e).__name__, e, "".join(traceback.format_exc().splitlines(True)[-6:]))
    secs = time.monotonic() - started
    if why:
        print("selftest FAILED in %.1f s: %s" % (secs, why), file=sys.stderr)
        return 1
    print("selftest ok in %.1f s" % secs)
    return 0
