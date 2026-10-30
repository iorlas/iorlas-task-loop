"""The engine tests' shared case: the fixtures, the helpers and the base class the per-feature test files build on."""
import atexit
import collections.abc
import contextlib
import functools
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from contracts import samples as S

from support import fake_route, gitsim, procsim
from support.builders import argv_cfg, cfg_with, make_engine
from support.checkpoints import flat_ck, stored_ck
from support.checks import res
from support.fakes import FakeBeadStore
from support.logs import records
from support.narrow import must
from support.procsim import real_proc  # noqa: F401
from support.push_race import PushRace
from support.waits import until
from taskloop.adapters import (
    applog,
    gitrepo,
    ident,
)
from taskloop.adapters import delegate as dl
from taskloop.adapters import delegate as lroute  # noqa: F401
from taskloop.adapters import halt as halting
from taskloop.app.asks import intake
from taskloop.app.release import seams
from taskloop.app.run import (
    engine,
    entry,
)
from taskloop.app.wire import slots as wslots
from taskloop.app.write.newfiles import NewFiles
from taskloop.contracts import wire
from taskloop.contracts.ask import AskAnswer
from taskloop.contracts.checks import CheckRun
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.plancheck import adhoc
from taskloop.contracts.stores import AskStore
from taskloop.domain import outcome as oc
from taskloop.domain.checks import (
    lint,  # noqa: F401
)
from taskloop.domain.lanes import netgate  # noqa: F401
from taskloop.domain.lanes import policy as lp  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]




sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def pid_gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def sh(*a, cwd):
    subprocess.run(list(a), cwd=cwd, check=True, capture_output=True)


POSIX_CHECK = unittest.skipIf(os.name == "nt", "the check is bash (operators, $VAR, rm, test, grep, sleep, /dev/null); "
                                              "on Windows the engine runs checks through cmd.exe")


ENGINE_BASH = unittest.skipIf(os.name == "nt", "the engine's own conflict-marker check (`! git grep ...`) is bash; cmd.exe cannot parse it")


def without_shims(fn):
    """A tool the machine's version manager shims but has not installed (mise: `ruff is not a valid shim`) exits 1, not 127:
    the test means a tool that is missing, so the shim directories leave PATH."""
    @functools.wraps(fn)
    def run(*a, **kw):
        keep = os.pathsep.join(d for d in os.environ.get("PATH", "").split(os.pathsep) if "shims" not in d)
        with mock.patch.dict(os.environ, {"PATH": keep}):
            return fn(*a, **kw)
    return run


EXIT_127 = unittest.skipIf(os.name == "nt", "the engine reads a missing tool as bash's exit 127; cmd.exe reports it as exit 1")


SH_FAKE = unittest.skipIf(os.name == "nt", "the bd fake is a #!/bin/sh script, which Windows cannot execute")


NO_FCNTL = unittest.skipIf(os.name == "nt", "the lock is fcntl; tl has none on Windows (documented no-op)")


def shq(text):
    """One shell word for the engine's check runner: bash quoting on POSIX, CreateProcess quoting for cmd.exe on Windows."""
    return shlex.quote(text) if os.name != "nt" else subprocess.list2cmdline([text])


def shown(p):
    """A path as git and the engine print it: forward slashes and long names on Windows."""
    return Path(p).resolve().as_posix() if os.name == "nt" else str(p)


PY = f'"{sys.executable}"'


def pyc(code, *args):
    """A check as its one-line text: this interpreter running `code`, then the arguments."""
    return shlex.join([sys.executable, "-c", code, *args])


HAS_F = "has-f"  # a procsim fake: exit 0 iff f.txt exists in the check's directory


FALSE = "false"  # a procsim fake: exit 1


RED_ONCE = "green-on-d3"  # a procsim fake (registered in setUp): exit 0 iff f.txt reads d3, red until the writer wrote it


PLAN: dict[str, Any] = {
    "summary": "do it",
    "stages": [
        {
            "goal": "add f",
            "files": ["f.txt"],
            "checks": [adhoc(HAS_F)],
            "hard": False,
            "anchors": [{"path": "f.txt", "lines": "1", "symbol": "", "why": "the file"}],
        }
    ],
    "risks": [],
    "question": "",
    "options": [],
    "decided": "",
    "cases": [],
    "leftovers": [],
}


WRITE = {
    "summary": "wrote f",
    "checks_run": [{"cmd": "test -f f.txt", "exit": 0}],
    "question": "",
    "options": [],
    "decided": "",
    "bad_checks": [],
    "new_cases": [],
    "unchecked": [],
    "logic_only": "",
}


ROUTE = "/h/.claude/plugins/cache/iorlas-marketplace/iorlas-delegate/%s/skills/delegate/route.py"


CLEAN = {
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


BEAD = {"id": "t-1", "title": "Add f", "metadata": {}, "acceptance_criteria": "f.txt exists"}


def review(unmet=(), findings=(), question="", decided=""):
    return dict(CLEAN, unmet=list(unmet), findings=list(findings), question=question, decided=decided)


def verdict(n, v, evidence="", why="", kind="other", source=""):
    return {"n": n, "verdict": v, "evidence": evidence, "why": why, "kind": kind, "source": source}


STILL_OPEN = {"items": [verdict(1, "open", why="only the owner can open it")]}


def stop(reason, ref="", **kw):
    """A stopped answer, contract 3: the row of `reason` in delegate's contract.json (kw: at, fix, partial, say, family, lane ...)."""
    return fake_route.stop_answer(reason, ref, **kw)


def full(data, ref="w2", **kw):
    """A done answer with its lane facts spelled out (a test where the lane, the family or the fallback fields differ)."""
    fields = {"cost": 0.5, "secs": 1, "family": "claude", "lane": "C", "model": "sonnet", "effort": "e",
                  "tokens": {"in": 1000, "cached": 800, "out": 50}, "context": {"instructions": [], "env_keys": []}}
    fields.update(kw)
    return fake_route.answer(fake_route.contract(), None, ref, False, data, **fields)


CAT_ENV = {"kind": "policy", "tool": "shell", "path": ".env", "input": {"command": "cat .env"}}


def finding(severity):
    return {"file": "f.txt", "line": 1, "severity": severity, "fix": f"a {severity} fix", "axis": "standards", "category": "logic",
            "scenario": "input x gives y" if severity == "high" else ""}


def no_sleep_here():
    """time.sleep skips the wait on the calling thread only (a patch on `time` itself is process-wide: a second thread then spins on a
    MagicMock that records every call, ~110 MB/s; see docs/dev/runaway-process.md). Other threads keep the real sleep."""
    real, owner = time.sleep, threading.get_ident()
    return mock.patch.object(time, "sleep", lambda secs: real(0) if threading.get_ident() == owner else real(secs))


def delegate_stack(script, route="/fake/route.py"):
    """The engine's delegate for a test: `route` resolved on fake_route's contract 3, `script` as the process seam, no real sleep."""
    res = dl.Resolved(Path(route).parent, route, fake_route.CONTRACT, "explicit")
    stack = contextlib.ExitStack()
    for p in (
        mock.patch.object(dl, "resolve", return_value=res),
        mock.patch.object(seams.DelegateRoute, "runner", lambda self, *a, **k: script),
        no_sleep_here(),
    ):
        stack.enter_context(p)
    return stack


_TEMPLATE = []
# No background git: a push's receive-pack and a commit run `gc --auto` / `maintenance run --auto` detached, writing into the
# repo (objects/maintenance.lock) while a test copytrees it. Env covers every git call, repo config covers the rest.
NO_GC = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "maintenance.auto", "GIT_CONFIG_VALUE_0": "false",
         "GIT_CONFIG_KEY_1": "gc.auto", "GIT_CONFIG_VALUE_1": "0"}


def _template():
    """origin (o.git) + clone (wt) with one pushed commit, built once per process: on a machine where every new file and
    process costs 5-30 ms (Defender) a copy is ~4x cheaper than the 5 git calls that make it."""
    if not _TEMPLATE:
        d = Path(tempfile.mkdtemp(prefix="tl-engine-template-"))
        atexit.register(shutil.rmtree, d, True)
        env = {**os.environ, **NO_GC}
        env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        def g(*a, cwd):
            subprocess.run(list(a), cwd=cwd, check=True, capture_output=True, env=env)
        g("git", "init", "-q", "--bare", "-b", "main", str(d / "o.git"), cwd=d)
        g("git", "clone", "-q", str(d / "o.git"), str(d / "wt"), cwd=d)
        for repo in ("o.git", "wt"):
            g("git", "config", "maintenance.auto", "false", cwd=d / repo)
            g("git", "config", "gc.auto", "0", cwd=d / repo)
        (d / "wt" / "a.txt").write_text("a\n")
        g("git", "add", "-A", cwd=d / "wt")
        g("git", "commit", "-qm", "init", cwd=d / "wt")
        g("git", "push", "-q", "origin", "HEAD:main", cwd=d / "wt")
        _TEMPLATE.append(d)
    return _TEMPLATE[0]


def copy_origin_and_clone(home):
    """Put a fresh o.git and wt in `home` (what five git calls used to build); the clone's origin URL is rewritten to `home`."""
    t = _template()
    for name in ("o.git", "wt"):
        shutil.copytree(t / name, home / name, ignore=shutil.ignore_patterns("*.sample"))
    cfg = home / "wt" / ".git" / "config"
    cfg.write_text(cfg.read_text().replace(str(t / "o.git"), str(home / "o.git")))


def real_git(reason):
    """A test that runs on a real git repo (origin + clone) instead of the gitsim: `reason`, one line, is what only real git can
    show. The marked cells are the integration set; every other engine test runs on the sim, and a real git spawned there fails it."""
    def mark(fn):
        fn.real_git = reason
        return fn
    return mark


def no_repo(fn):
    """The test calls code directly and never touches the repo: setUp skips building origin and clone."""
    fn.no_repo = True
    return fn


def read_ask(bead="t-1") -> Any:
    """The bead's ask record as the dict on disk, or None."""
    p = ident.config_dir() / "asks" / (f"{bead}.json")
    return json.loads(p.read_text()) if p.exists() else None


def card_of(a):
    """All the text the owner reads on an ask record: the decision, what was tried, the options, and the details."""
    opts = " ".join("{} {}".format(o["label"], o["consequence"]) for o in a["options"])
    return " ".join([a["decision"], " ".join(a["tried"]), opts, a["detail"]["text"], a["why"]])


def ask_rec(**over):
    """A current-version ask record as a dict, open and unanswered, with fields overridden."""
    base = wire.dump(S.ASK)
    return {**base, "status": "open", "answer": None, "answered": None, "consumed": None, **over}


class Recorded(collections.abc.Sequence):
    """What the engine did to its bead, read off the fake bd's recorded writes each time it is looked at (a list that follows the store)."""

    def __init__(self, read):
        self.read = read

    def __getitem__(self, i):
        return self.read()[i]

    def __len__(self):
        return len(self.read())

    def __eq__(self, other):
        return self.read() == list(other)

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self):
        return repr(self.read())


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.env = mock.patch.dict(
            os.environ,
            {
                "XDG_CONFIG_HOME": str(home / "cfg"),
                "APPDATA": str(home / "cfg"),
                "CLAUDE_CODE_SESSION_ID": "sess1234-x",
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
                "BEADS_DIR": str(home / "no-beads"),
                **NO_GC,
            },
        )  # a bd that slips past the store finds nothing to write
        self.env.start()
        self.wt = home / "wt"
        method = getattr(self, self._testMethodName)
        self.sim = None
        if not getattr(method, "real_git", None):
            gitsim.reset()
            self.sim = gitsim.Sim(self)
            stack = contextlib.ExitStack()
            self.addCleanup(stack.close)
            self.sim.install(stack)
            if not getattr(method, "no_repo", False):
                gitsim.new_world(home)
        elif not getattr(method, "no_repo", False):
            copy_origin_and_clone(home)
        procsim.fake(engine.Engine.MARKERS, procsim.markers)
        procsim.fake(f"{shlex.quote(sys.executable)} /fake/route.py net", procsim.exits(2, "no such file"))  # the network probe: no answer
        procsim.fake(RED_ONCE, lambda cwd, env: (0 if procsim.f_txt(cwd) == "d3" else 1, ""))
        self.store = FakeBeadStore()  # bd, show and comments of every engine this test builds (pass store=self.store)
        self.bd_calls = self.store.calls
        self.closed = Recorded(lambda: [c[3] for c in self.store.said("close")])  # the reasons the engine closed its bead with
        self.blocked = Recorded(
            lambda: [c[3].removeprefix("Blocked: ") for c in self.store.said("comments", "add") if c[3].startswith("Blocked: ")]
        )
        self.lands = Recorded(
            lambda: [c for c in self.store.said("provenance", "record") if c[5] == "land"]
        )  # the land records in bd's provenance

    def commit_base_cfg(self, engine_cfg):
        base = Path(self.tmp.name, "base-cfg")
        if not base.exists():
            sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        sh("git", "pull", "-q", "origin", "main", cwd=base)
        (base / ".task-loop.json").write_text(json.dumps({"engine": argv_cfg(engine_cfg)}))
        sh("git", "add", "-A", cwd=base)
        sh("git", "commit", "-qm", "engine config", "--allow-empty", cwd=base)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)

    def put_repo_file(self, rel, text):
        """A file committed to origin/main (the engine's worktree starts from it)."""
        base = Path(self.tmp.name, "base-cfg")
        if not base.exists():
            sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        sh("git", "pull", "-q", "origin", "main", cwd=base)
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_text(text)
        sh("git", "add", "-A", cwd=base)
        sh("git", "commit", "-qm", "add " + rel, cwd=base)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)

    def tearDown(self):
        applog.close_all()  # tl-64i: the held log handles live in the temp dir that goes now
        self.env.stop()
        self.tmp.cleanup()
        if self.sim:
            self.sim.check()

    def fake_bd(self, *a, **kw):
        return mock.Mock(returncode=0, stdout="", stderr="")  # the store records the call itself

    def run_engine(self, answers, route="/fake/route.py", raw=None, j_extra=None, bead="t-1", probe=None, prep=None, **cfg):
        """`raw` puts keys in the loaded config without committing them. probe: the network probe (netgate.FakeProbe). prep: called
        with the engine before it runs."""
        script = fake_route.Script(answers, j_extra)
        c = wslots.load_cfg(str(self.wt))
        fresh = cfg.pop("fresh", False)
        c = cfg_with(c, **{"reflect": False, **cfg, **(raw or {})})  # the reflection is one more call; its own tests switch it on
        with delegate_stack(script, route):
            self.eng = engine.Engine(BeadId(bead), str(self.wt), c, store=self.store, fresh=fresh)
            if probe is not None:
                self.eng.probe = probe
            if prep is not None:
                prep(self.eng)
            rc = self.eng.run()
        return rc, script

    def checks_engine(self, attrs=None, **cfg):
        return make_engine(self.wt, cfg=cfg, store=self.store, attrs=attrs)

    LOCK: ClassVar[Any] = ["Unable to create project: It looks like another Unity instance is running with this project open.",
            "Multiple Unity instances: Temp/UnityLockfile in use", "another Unity instance has the project open"]

    def counting_check(self, line, ok_after=None):
        """A check (a procsim fake) that prints `line` and exits 1, counting its runs in a file; green from run ok_after on."""
        n = Path(self.tmp.name) / (f"runs-{self._testMethodName}")

        def run(cwd, env):
            k = (int(n.read_text()) if n.exists() else 0) + 1
            n.write_text(str(k))
            return (0 if ok_after is not None and k >= ok_after else 1), line
        return procsim.fake(shlex.join(["count-check", n.name, line]), run), n

    R10 = "R10: a general rule never names a single item"

    def asks_the_owner(self, q):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [review(question=q)]})
        self.assertEqual(rc, 2)
        self.assertEqual(self.ask()["kind"], "decision")
        self.assertIn(q, self.blocked[-1])

    def spawn(self, pidfile, term=False):
        """A check that starts a child sleeping 30 s and records its pid, then waits for it (term: after sending its parent, the
        engine, SIGTERM)."""
        kill = "kill -TERM $PPID; " if term else ""
        script = Path(pidfile).with_suffix(".sh")  # a script, not `sh -c`: a check is an argv, and a shell string is refused
        script.write_text(f"sleep 30 &\necho $! > {shlex.quote(str(pidfile))}\n{kill}wait\n")
        return shlex.join(["sh", str(script)])

    def script(self, name, body):
        """A shell script in the test's temp dir, as the one-line text of a command that runs it."""
        path = Path(self.tmp.name, name)
        path.write_text(body)
        return shlex.join(["sh", str(path)])

    def child_of(self, pidfile, limit=5):
        """The pid the check recorded. A caller that waits for a loaded runner to start the check passes a long limit (the wait ends
        the moment the pid is there; the limit is only the give-up)."""
        if until(lambda: pidfile.exists() and pidfile.read_text().strip(), limit):
            return int(pidfile.read_text())
        self.fail("the check never started its child")

    def assertDead(self, pid):
        if not until(lambda: pid_gone(pid), 3):
            os.kill(pid, 9)
            self.fail(f"pid {pid} outlived the engine's stop")

    def stoppable(self):
        """The engine's own SIGTERM handler (run_main installs it), restored after the test."""
        if os.name == "nt":
            self.skipTest("POSIX signals")

        return halting.halt_on_sigterm()

    ANCHORS: ClassVar[Any] = [{"path": "f.txt", "lines": "1", "symbol": "", "why": "the file"}]

    TWO: ClassVar[Any] = {
        "summary": "two",
        "stages": [
            {"goal": "stage one", "files": ["f.txt"], "checks": [adhoc(HAS_F)], "hard": False, "anchors": ANCHORS},
            {"goal": "stage two", "files": ["f.txt"], "checks": [adhoc(HAS_F)], "hard": False, "anchors": ANCHORS},
        ],
        "risks": [],
        "question": "",
        "options": [],
        "decided": "",
        "cases": [],
        "leftovers": [],
    }

    def stop_at(self, role, nth):
        """The nth call of a role is where the engine is stopped (SIGTERM raises Blocked in the main thread)."""
        real, seen = fake_route.Script.reply, {"n": 0}

        def call(this, r, *a, **kw):
            if r == role:
                seen["n"] += 1
                if seen["n"] == nth:
                    raise engine.Blocked("failed: stopped (SIGTERM)", kind=oc.Kind.PAUSE_KILLED)
            return real(this, r, *a, **kw)
        return mock.patch.object(fake_route.Script, "reply", call)

    def checkpoint(self) -> dict[str, Any]:
        ck = flat_ck(stored_ck())
        assert ck is not None, "no checkpoint is stored"
        return ck

    def assertNoCheckpoint(self):
        self.assertIsNone(flat_ck(stored_ck()))

    def reclaim(self, bead, comments=(), ask=None, live=()):
        if ask:
            p = ident.config_dir() / "asks" / "t-1.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(ask))
        leases = [
            dict(BEAD, id=f"live-{n}", status="in_progress", assignee=who, lease_expires_at="2999-01-01T00:00:00Z")
            for n, who in enumerate(live)
        ]
        with self.store.stub(show=dict(BEAD, **bead), comments=list(comments), find_fn=lambda q: leases):
            ok, why = entry.reclaim("t-1", str(self.wt), store=self.store)
        updates = [c for c in self.bd_calls if c[:1] == ("update",)]
        return ok, why, updates

    BLOCKED: ClassVar[Any] = {"author": "tl-61ba34e7", "text": "Blocked: failed: write node produced no valid output",
               "created_at": "2026-10-20T21:11:48Z"}

    def plan_with(self, *checks):
        return dict(PLAN, stages=[dict(PLAN["stages"][0], checks=list(checks))])

    RED_ONCE = RED_ONCE

    MARK = "BRIEF-MARKER-4f1c"

    def two_writes(self, family="claude", ctx_k=None, **cfg):
        """A red check sends the stage back to the same writer once. ctx_k: how big the first session ended, in k."""
        path = Path(self.tmp.name, "session.jsonl")
        if ctx_k is not None:
            n = int(ctx_k * 1000) - 100
            line = ({"type": "assistant", "message": {"usage": {"input_tokens": 3, "cache_read_input_tokens": n,
                                                                "cache_creation_input_tokens": 97}}} if family == "claude" else
                    {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": n + 100}}}})
            path.write_text(json.dumps({"type": "user"}) + "\n" + json.dumps(line) + "\n" + json.dumps({"type": "system"}) + "\n")
        extra = {"family": family, "transcript": str(path) if ctx_k is not None else ""}
        with self.store.stub(show=dict(BEAD, description="Add the file f. " + self.MARK)):
            return self.run_engine({"plan": [self.plan_with(self.RED_ONCE)], "write": [WRITE, WRITE], "review": [CLEAN]},
                                   j_extra={"write": [extra, extra]}, **cfg)

    def run_push_race(self, rejections=1, failure="", plan=PLAN, resume_failed_fix=False, **cfg):
        """Advance a local remote immediately before each rejected push, under the real land lock (support/push_race.py)."""
        self.race_runs = getattr(self, "race_runs", 0) + 1
        cfg.setdefault("land_optimistic_tries", 0)  # these cells: the gate inside one lock (the outside gate: test_gate_outside_lock)
        race = PushRace(self, self.race_runs, rejections, failure)
        self.race_origin = race.origin
        return race.run(plan, resume_failed_fix, cfg, CLEAN, WRITE, review(findings=[finding("high")]))

    def wait_records(self, eng):
        if not Path(eng.log_path).exists():
            return []
        return records(eng, "wait_end")

    def counter(self, name):
        """A check (a procsim fake) that adds one '1' to a file per run: (the file, the check)."""
        f = Path(self.tmp.name, name)

        def run(cwd, env):
            with f.open("a") as out:
                out.write("1")
            return 0, ""
        return f, procsim.fake(f"count {name}", run)

    def said(self):
        """The engine's own comments (Engine failed / Engine paused): where a machine fault or pause now says why."""
        return "\n".join(c[3] for c in self.bd_calls if c[:2] == ("comments", "add") and str(c[3]).startswith("Engine "))

    def ask(self) -> Any:
        return read_ask()

    def card(self):
        return card_of(self.ask())

    def asks(self):
        return AskStore.at(ConfigDir(ident.config_dir()))

    def file_answer(self, action, text="", bead="t-1"):
        """The owner answers the bead's ask the way the dashboard and `tl answer` do: an AskAnswer record, never a comment."""
        a = must(self.asks().get(bead))
        return self.asks().answer(bead, a.id, AskAnswer(action=action, text=text, t=time.time(), by="denis"))

    CHOICES: ClassVar[Any] = [{"label": "Build it", "cost": "about 4 stages", "answer": "A: build the slice now", "recommended": False},
               {"label": "Keep parked", "cost": "none", "answer": "B: keep it parked", "recommended": True},
               {"label": "", "cost": "x", "answer": "dropped: no label", "recommended": False}]

    def verify_then_answer(self, action, text=""):
        r = dict(CLEAN, unchecked=[{"what": "the cited spec link did not open", "kind": "link"}])
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r], "verify": [STILL_OPEN]})
        self.file_answer(action, text)
        return [{"author": "engine", "text": "Ask (engine) t-1-1 (decision): check the link"}]

    GAPS: ClassVar[Any] = [{"what": "the hand-written .meta matches its siblings and its guid is unique", "kind": "tooling"},
            {"what": "Boot() calls the new Wire()", "kind": "requirement"},
            {"what": "the menu reads well on a phone", "kind": "requirement"}]

    def verified(self, answer, **kw):
        answers = {"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN, unchecked=self.GAPS)], "verify": [answer]}
        for k, v in kw.items():
            answers[k] = v
        return self.run_engine(answers)

    RESEARCH_DIFF = ("diff --git a/notes/hair.md b/notes/hair.md\n--- a/notes/hair.md\n+++ b/notes/hair.md\n@@ -0,0 +1,3 @@\n"
                     "+Dread packs: https://fab.com/s/abc is free.\n+Beards: (unverified) https://sketchfab.com/m/x blocks agents.\n"
                     "+Docs: https://docs.unity3d.com/Manual/index.html\n")

    BAD_SCHEMA = ("codex rejected the request: {\"type\":\"error\",\"error\":{\"message\":\"Invalid schema for response_format "
                  "'codex_output_schema': Missing 'accept_files'.\",\"code\":\"invalid_json_schema\"},\"status\":400}")

    def bad_request(self, **kw):
        return stop("bad_request", family="openai", text=self.BAD_SCHEMA, say=self.BAD_SCHEMA, **kw)

    def stopped_run(self, bead=BEAD, plan=PLAN, answers=None):
        """A run on `bead` stopped in its first review: its checkpoint holds the plan."""
        with self.stop_at("reviewer", 1), self.store.stub(show=bead):
            return self.run_engine(answers or {"plan": [plan], "write": [WRITE]})

    def engine_noise(self, name):
        """Notes lines and comments the engine wrote, from the stored brief of a run that was cap-parked (tests/fixtures/briefs)."""
        notes, comments = stored_brief(name)
        last = [
            ("tl-x", ln)
            for ln in re.findall(r"(?m)^(?:Blocked:|Reflect \(engine\)).*$", (BRIEFS / (name + ".md")).read_text(encoding="utf-8"))
        ]
        return [{"author": a, "text": t} for a, t in comments + last if intake.engine_written(t)] + [
            {"author": "tl-x", "text": "Engine paused: paused: no lane for write until 10:00 (no_lane: Hold the task)"}], notes


class StrayWriteScript(fake_route.Script):
    """A writer whose play-mode run leaves Unity's scene and its .meta behind (lifesim-fld.6)."""

    def reply(self, role, prompt, schema, cwd, resume, *a, **kw):
        if role == "worker":
            d = Path(cwd, "client", "Assets")
            d.mkdir(parents=True, exist_ok=True)
            (d / "InitTestScene123.unity").write_text("scene\n")
            (d / "InitTestScene123.unity.meta").write_text("meta\n")
        return super().reply(role, prompt, schema, cwd, resume, *a, **kw)




BRIEFS = ROOT / "tests" / "fixtures" / "briefs"


CAP_PARKS = (
    "lifesim-o67g-20261025-005827",
    "lifesim-yxbb.2-20261024-014147",
    "lifesim-d5f.40-20261025-071741",
)  # the runs of o67g 10-25 00:58, yxbb.2 10-24 01:41, d5f.40 10-25 07:18


def stored_brief(name):
    """(notes, [(author, text)]) read back out of a stored brief.md: the sections the engine's own records leaked into."""
    text = (BRIEFS / (name + ".md")).read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## ", text)
    sec = {p.split("\n", 1)[0]: ([*p.split("\n", 1), ""])[1] for p in parts[1:]}
    comments = []
    for line in (sec.get("Comments") or "").splitlines():
        m = re.match(r"- ([^:\n]+): (.*)$", line)
        if m:
            comments.append((m.group(1), m.group(2)))
        elif comments and line.strip():
            comments[-1] = (comments[-1][0], comments[-1][1] + "\n" + line)
    return sec.get("Notes", "").strip(), comments


if __name__ == "__main__":
    unittest.main()


def _cells(owner, prefix, cell, cases):
    """One test per cell of a table (a subTest loop run as one test is one long test the shards cannot split)."""
    for args in cases:
        def run(self, args=args):
            getattr(self, cell)(*args)
        run.__name__ = re.sub(r"\W+", "_", "test_{}_{}".format(prefix, "_".join(str(a).lower() for a in args)))
        setattr(owner, run.__name__, run)


class LandReviewBase(EngineTest):
    STRAY: ClassVar[Any] = ["client/Assets/InitTestScene123.unity", "client/Assets/InitTestScene123.unity.meta"]

    def engine_at_land(self, attrs=None, **cfg):
        plan = {"stages": [{"goal": "g", "files": ["f.txt", "docs/"], "checks": [], "hard": False}]}
        return make_engine(self.wt, cfg=cfg, store=self.store, attrs=dict({"plan_data": plan}, **(attrs or {})))

    def staged(self):
        return sorted(gitrepo.git("diff", "--cached", "--name-only", cwd=str(self.wt)).split())

    def make_files(self, *names):
        for n in names:
            (self.wt / n).parent.mkdir(parents=True, exist_ok=True)
            (self.wt / n).write_text("x\n")

    def run_with(self, script):
        with delegate_stack(script, "/r.py"):
            self.eng = engine.Engine(BeadId("t-1"), str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
            return self.eng.run()

    def landed(self):
        return sorted(gitrepo.git("show", "--name-only", "--format=", "origin/main", cwd=str(self.wt)).split())

    CFG_CHECKS: ClassVar[Any] = [{"id": "unity-analyzers", "cmd": "just unity-analyzers", "group": "static"},
                  {"id": "unity-tests", "cmd": "just unity-tests", "group": "tests"},
                  {"id": "unity-play-tests", "cmd": "just unity-play-tests", "group": "tests"}]

    def verifier(self, attrs=None, **cfg):
        return self.engine_at_land(dict({
            "unchecked": [], "verified": [], "steps": mock.Mock(), "comment": mock.Mock(),
            "briefs": types.SimpleNamespace(text=lambda: "the task"), "last_flag": ""}, **(attrs or {})), **cfg)

    YXBB6 = ("I did not re-run the whole Sim.Properties suite or the just unity-* checks. The engine ran the suite, and it "
             "passed. The unity checks were skipped because nothing changed under client/**... the claim that the engine ran "
             "the suite has no saved log, so I cannot prove it.")

    SUITE = "tests/Sim.Properties/bin/Debug/net10.0/Sim.Properties --filter-class '*SleepSkipTests'"

    def engine_checks(self, **over):
        rows = [
            res("just fmt-check", 0, id="fmt", group="static", secs=4, log="checks/00-fmt.r1.log"),
            res("just unity-analyzers", None, id="unity-analyzers", group="static", why="no change under client/**"),
            res("just unity-tests", None, id="unity-tests", why="no change under client/**, content/**"),
            res(self.SUITE, 0, id=self.SUITE, group="acceptance", secs=3, log="checks/06-tests_Sim.Properties.r2.log", tail="succeeded: 4"),
        ]
        return [r.replace(**over.get(r.id, {})) for r in rows]

    def evidenced(self, checks=None, attrs=None):
        e = self.verifier(attrs, checks=self.CFG_CHECKS[:2], gate="just check")
        e.last_run = CheckRun(round=1, tree=e.checkout.tree_hash(), results=checks or self.engine_checks())
        return e

    def reviewer_brief(self, cap=40000):
        script = fake_route.Script({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        with mock.patch.object(NewFiles, "STAGE_DIFF_CAP", cap):
            self.assertEqual(self.run_with(script), 0)
        return next(p for c, p in zip(script.calls, script.prompts, strict=False) if c[0] == "reviewer")
