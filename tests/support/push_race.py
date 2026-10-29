"""A land whose push is rejected because main moved: a local origin that a second clone advances right before each rejected push, with
the real land lock held around the land and a trace of what ran inside it (events). Used by EngineTest.run_push_race."""
import os
import signal
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

from support.checks import res
from taskloop.app.land.checkout import Checkout
from taskloop.app.land.fixer import Fixer
from taskloop.app.land.lander import Lander
from taskloop.app.land.outbound import land_argv
from taskloop.app.run import engine
from taskloop.app.run.waits import Waits
from taskloop.contracts.checks import CheckRun
from taskloop.contracts.enums import WaitWhat

RETRY_RED = ("checks", "checks_fixed", "checks_exhausted", "review_exhausted")


def sh(*a, cwd):
    subprocess.run(list(a), cwd=cwd, check=True, capture_output=True)


def seam(method):
    """A function that, set on a class, calls `method` with the instance as its first argument (a bound method set there would not)."""
    def call(this, *a, **kw):
        return method(this, *a, **kw)
    return call


class PushRace:
    def __init__(self, case, n, rejections, failure):
        self.case, self.n, self.rejections, self.failure = case, n, rejections, failure
        self.home = Path(case.tmp.name)
        case.wt = self.home / f"race-{n}"
        self.origin = self.home / f"race-origin-{n}.git"
        sh("git", "clone", "-q", "--bare", str(self.home / "o.git"), str(self.origin), cwd=self.home)
        self.other = self.home / f"concurrent-{n}"
        for checkout in (case.wt, self.other):
            sh("git", "clone", "-q", str(self.origin), str(checkout), cwd=self.home)
        self.events: list[str] = []
        self.held: list[bool] = []
        self.state: dict[str, Any] = {"pushes": 0, "fetches": 0, "gates": 0, "results": []}
        self.real = {"lock": Lander.lock, "sh": engine.Engine.sh, "wait": Waits.add, "fetch": Checkout.fetch,
                     "checks": engine.Engine.run_checks, "fix": Fixer.fix}
        self.gate = ["true"]

    # -- the seams, each called with the object it replaces a method of as `this` ----------------------------------------------

    @contextmanager
    def lock(self, this):
        with self.real["lock"](this):
            self.case.assertFalse(self.held)
            self.held.append(True)
            self.events.append("enter")
            try:
                yield
            finally:
                self.events.append("exit")
                self.held.pop()

    def fetch(self, this, *a, **kw):
        if self.held:
            self.events.append("fetch")
            self.state["fetches"] += 1
            if self.failure == "fetch" and self.state["fetches"] == 2:
                return 1, "fetch failed"
        return self.real["fetch"](this, *a, **kw)

    def checks(self, this, st, name, *a, **kw):
        state = self.state
        if name == "land retry":
            self.case.assertTrue(self.held)
            self.events.append("checks")
            if self.failure == "checks_stop":
                state["pidfile"] = self.home / f"retry-child-{self.n}.pid"
                state["next_check"] = self.home / f"retry-next-{self.n}"
                st = dict(st, checks=[self.case.spawn(state["pidfile"], term=True), f"touch {state['next_check']}"])
            if self.failure in RETRY_RED and not state.get("check_failed"):
                state["check_failed"] = True
                return CheckRun(round=0, results=[res("retry check", 1, tail="red")])
        result = self.real["checks"](this, st, name, *a, **kw)
        if self.failure == "checks_exhausted" and (name.startswith("fix ") or state.get("resuming")):
            red = {"status": "failed", "exit": 1, "tail": "still red"}
            result = result.replace(results=[c.replace(**red) for c in result])
        if state.get("resuming"):
            state.setdefault("resume_checks", []).append(result)
        if name == "land retry":
            state["results"].append(result)
        return result

    def command(self, this, cmd, *a, **kw):
        state = self.state
        if self.held and isinstance(cmd, list) and cmd[:3] == ["git", "rebase", "-q"]:
            self.events.append("rebase")
        if self.held and cmd == self.gate:
            self.events.append("gate")
            state["gates"] += 1
            if self.failure == "gate" and state["gates"] == 2:
                return 1, "gate red"
        if cmd == land_argv(this.cfg.land):
            self.case.assertTrue(self.held)
            self.events.append("push")
            state["pushes"] += 1
            if state["pushes"] <= self.rejections:
                self.advance_origin(state["pushes"])
            elif self.failure in ("network", "push", "stop"):
                if self.failure == "stop":
                    signal.raise_signal(signal.SIGTERM)
                    return 1, "! [rejected] (fetch first)"
                return 1, "Connection reset" if self.failure == "network" else "hook failed"
        return self.real["sh"](this, cmd, *a, **kw)

    def advance_origin(self, pushes):
        path = "f.txt" if self.failure == "conflict" else "a.txt"
        (self.other / path).write_text(f"concurrent {pushes}\n")
        sh("git", "add", "-A", cwd=self.other)
        sh("git", "commit", "-qm", "concurrent", cwd=self.other)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.other)

    def fix(self, this, kind, tail, resume=False):
        self.case.assertFalse(self.held)
        self.events.append("fix:" + kind)
        if self.failure in ("checks_fixed", "checks_exhausted", "review_exhausted"):
            self.state["fix_result"] = self.real["fix"](this, kind, tail, resume)
            return self.state["fix_result"]
        raise engine.Blocked("test stops at fix: " + kind)

    def wait(self, this, secs, what, wid=None):
        if what != WaitWhat.NETWORK:
            return self.real["wait"](this, secs, what, wid)
        self.case.assertFalse(self.held)
        self.events.append("wait")
        raise engine.Blocked("test stops at network wait")

    # -- the run ---------------------------------------------------------------------------------------------------------------

    def run(self, plan, resume_failed_fix, cfg, clean, write, review_with_finding):
        case, state = self.case, self.state
        config_home = str(self.home / f"race-cfg-{self.n}")
        state["config_home"] = config_home
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": config_home, "APPDATA": config_home}), \
                mock.patch.object(Lander, "lock", seam(self.lock)), \
                mock.patch.object(Checkout, "fetch", seam(self.fetch)), \
                mock.patch.object(engine.Engine, "run_checks", seam(self.checks)), \
                mock.patch.object(engine.Engine, "sh", seam(self.command)), \
                mock.patch.object(Fixer, "fix", seam(self.fix)), \
                mock.patch.object(Waits, "add", seam(self.wait)):
            reviews = [clean, review_with_finding] if self.failure == "review_exhausted" else [clean] * 2
            rc, _ = case.run_engine({"plan": [plan], "write": [write] * 2, "review": reviews}, gate=self.gate, **cfg)
            if resume_failed_fix:
                rc = self.resume(plan, cfg, write, reviews[-1], rc)
        case.assertFalse(self.held)
        return rc, self.events, state

    def resume(self, plan, cfg, write, last_review, first_rc):
        case, state = self.case, self.state
        state["first_rc"], state["first_blocked"] = first_rc, case.said()
        state["checkpoint"] = case.checkpoint()
        state["resuming"] = True
        # An owner comment answers the stuck ask without discarding the checkpoint.
        with case.store.stub(comments=[{"author": "owner", "text": "Run again."}]):
            rc, script = case.run_engine({"plan": [plan], "write": [write], "review": [last_review]},
                                         gate=self.gate, **dict(cfg, max_replans=1))
        state["resume_calls"] = [c[0] for c in script.calls]
        return rc
