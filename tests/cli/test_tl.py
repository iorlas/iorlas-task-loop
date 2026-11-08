"""The tl.py launcher: its verbs and output."""
import io
import json
import os
import shutil
import stat
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import homes  # noqa: E402
from support.spawn import port_git  # noqa: E402

from taskloop.adapters import delegate as dl  # noqa: E402
from taskloop.app.wire import usage as usage_cmd  # noqa: E402
from tlkernel.env import snapshot  # noqa: E402
from tlkernel.rowstores import PinStore, ReposStore  # noqa: E402
from tlrelease import pinning  # noqa: E402

# isort: split
import contextlib  # noqa: E402

import tl  # noqa: E402
from contracts import samples as S  # noqa: E402
from support import (  # noqa: E402
    tlbd,
)
from support.spawn import real_spawner  # noqa: E402
from support.tlmain import tl_main  # noqa: E402
from support.who import who  # noqa: E402

from taskloop.app.launch import loop_start as wstart  # noqa: E402
from taskloop.app.track import trail  # noqa: E402
from taskloop.app.wire import asks as wasks  # noqa: E402
from tlkernel import wire  # noqa: E402
from tlkernel.ask import Ask  # noqa: E402
from tlkernel.askstore import AskStore  # noqa: E402
from tlkernel.ids import BeadId  # noqa: E402
from tlkernel.paths import ConfigDir  # noqa: E402
from tltestkit.checked import run_checked  # noqa: E402
from tltestkit.narrow import must  # noqa: E402


def ctx() -> tl.Ctx:
    """The verbs' context from the environment as the test set it up (the edge's own way)."""
    env = snapshot()
    return tl.Ctx(tl.HERE, trail.now, [], env, spawner=real_spawner(), git=port_git(), who=who())


def sh(*args, cwd):
    run_checked(list(args), cwd)


class Base(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.home = Path(self.tmp.name)
        env = {"XDG_CONFIG_HOME": str(self.home / "cfg"), "APPDATA": str(self.home / "cfg"),
               "CLAUDE_CODE_SESSION_ID": "abcdef12-3456", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        os.environ.pop("TASK_LOOP_ACTOR", None)

    def teardown_method(self):
        self.env.stop()

        def force(fn, path, _):  # Windows: git's pack files are read-only
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        shutil.rmtree(self.tmp.name, onerror=force)
        with contextlib.suppress(OSError):
            self.tmp.cleanup()


class OldLayout(Base):
    def test_a_command_on_an_old_config_dir_stops_and_names_the_migrate_command_and_migrate_runs(self):
        old = self.home / "cfg" / "task-loop" / "engine"
        old.mkdir(parents=True)
        (old / "t-1-20261015-100000.jsonl").write_text("{}\n")
        r = tl_main("status", cwd=self.home)
        assert (r.returncode, "tl layout migrate" in r.stderr) == (os.EX_CONFIG, True)
        r = tl_main("layout", "migrate", cwd=self.home)
        assert (r.returncode, "migrated 1 places" in r.stdout) == (0, True)
        assert (self.home / "cfg" / "task-loop" / "runs" / "t-1-20261015-100000" / "engine.jsonl").exists()
        assert "old layout" not in tl_main("layout", "migrate", cwd=self.home).stderr


class Identity(Base):
    def test_actor_is_per_session(self):
        assert who().actor == "tl-abcdef12"

    def test_actor_without_session_id_is_still_per_process(self):
        os.environ.pop("CLAUDE_CODE_SESSION_ID")
        os.environ["CLAUDE_PID"] = "4242"
        assert who().actor.endswith("-4242")

    def test_actor_override(self):
        os.environ["TASK_LOOP_ACTOR"] = "me"
        assert who().actor == "me"

    def test_config_dir_is_created(self):
        assert homes.config_dir().is_dir()


class Records(Base):
    def test_event_appends_and_registers_repo(self):
        trail.event(who(),"claim", "x-1", repo=str(self.home), worktree="/w")
        trail.event(who(),"close", "x-1", repo=str(self.home))
        lines = (homes.config_dir() / "events.jsonl").read_text().splitlines()
        assert [json.loads(ln)["kind"] for ln in lines] == ["claim", "close"]
        assert json.loads(lines[0])["session"] == "abcdef12-3456"
        assert ReposStore(homes.cfg()).known() == [str(self.home)]

    @pytest.mark.skipif(os.name == "nt", reason="the registry lock is fcntl")
    def test_writers_registering_at_once_neither_crash_nor_lose_a_repo(self):
        # race test (tl-bxk.11.1): every process wrote repos.tmp; the second os.replace found it gone and the event
        # (a claim's, a slot take's) raised. Each writer now has its own tmp file, under a lock, so none is lost.
        errs = []

        def writer(n):
            try:
                for i in range(10):
                    trail.register_repo(f"/r/{n}-{i}", homes.cfg())
            except Exception as e:
                errs.append(e)
        ps = [threading.Thread(target=writer, args=(n,)) for n in range(5)]  # the lock is on the open file: two descriptors conflict
        for p in ps:
            p.start()
        for p in ps:
            p.join(60)
        assert errs == []
        repos = wire.dump(ReposStore(homes.cfg()).index())["repos"]
        assert len(repos) == 50

    def test_prune_keeps_recent(self):
        f = homes.config_dir() / "events.jsonl"
        old = json.dumps({"t": 0, "kind": "old"})
        new = json.dumps({"t": trail.now(), "kind": "new"})
        f.write_text((old + "\n") * 120000 + new + "\n")
        trail.prune_events(homes.cfg())
        assert [json.loads(ln)["kind"] for ln in f.read_text().splitlines()] == ["new"]


class UsageCLI(Base):
    def test_usage_feeds_delegate(self):
        got = []

        def status(reading):
            got.append(reading)
            return {"ts": 1.0, "accounts": {"CLAUDE_SUBSCRIPTION": {"five": 6.0, "week": 4.0, "out": False}},
                    "cockpit": {"accounts": [{"id": "CLAUDE_SUBSCRIPTION", "state": "ready"}]}}
        with mock.patch.object(dl, "status_json", side_effect=status):
            out = io.StringIO()
            with mock.patch.object(sys, "stdout", out):
                rc = usage_cmd.feed("[]", real_spawner(), snapshot())
        assert rc == 0, out.getvalue()
        assert "5h 6.0%, week 4.0%" in out.getvalue()
        assert got == [[]]


class TraceCLI(Base):
    def test_trace_lists_runs_and_sessions_of_a_bead(self):
        cfg = self.home / "cfg" / "task-loop"
        cfg.mkdir(parents=True)
        run = {"v": 1, "run": "b-1-20261019-010000", "bead": "b-1", "outcome": "landed", "started": 0, "ended": 600,
               "cost": 0, "coordinator_session": "c1",
               "sessions": [{"node": "write", "role": "worker", "family": "openai", "status": "done", "ref": "thr-9"}]}
        other = dict(run, run="b-2-x", bead="b-2")
        (cfg / "traces.jsonl").write_text(json.dumps(run) + "\n" + json.dumps(other) + "\n")
        r = tl_main("trace", "b-1", cwd=self.home, env={"HOME": str(self.home)})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "b-1-20261019-010000  b-1  landed  10 min" in r.stdout
        assert "thr-9" in r.stdout
        assert "b-2-x" not in r.stdout


class SlotReset(Base):
    """A slot reset must never lose a dead session's work."""

    def setup_method(self):
        super().setup_method()
        self.origin = self.home / "origin.git"
        self.repo = self.home / "repo"
        sh("git", "init", "-q", "--bare", "-b", "main", str(self.origin), cwd=self.home)
        sh("git", "clone", "-q", str(self.origin), str(self.repo), cwd=self.home)
        (self.repo / "a.txt").write_text("a\n")
        (self.repo / ".gitignore").write_text("ignored/\n")
        sh("git", "add", "-A", cwd=self.repo)
        sh("git", "commit", "-qm", "init", cwd=self.repo)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.repo)
        (self.repo / ".task-loop.json").write_text(json.dumps({"slots": {"count": 1}}))
        self.slot = self.repo / ".slots" / "s1"
        sh("git", "worktree", "add", "-q", "--detach", str(self.slot), "origin/main", cwd=self.repo)
        self.cwd = os.getcwd()
        os.chdir(self.repo)
        # a reset is about git; the slot-bead lookup gets an empty bd, so no real bd (absent on CI) is needed
        tlbd.install(self, result=tlbd.done("[]"))

    def teardown_method(self):
        os.chdir(self.cwd)
        super().teardown_method()

    def reset(self, bead):
        return tl.main(["slot", "reset", "s1", "--bead", bead])


class PinAndRollback(Base):
    """pinned.json and the verbs that write it, against a scratch CLAUDE_CONFIG_DIR laid out as the plugin cache is."""

    def setup_method(self):
        super().setup_method()
        self.claude = self.home / "claude"
        p = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.claude)})
        p.start()
        self.addCleanup(p.stop)
        # the Mac standing pin asks origin for a devbox-ok tag (tests/release/test_canary.py): these are about the pin file
        off_mac = mock.patch.object(pinning.sys, "platform", "linux")
        off_mac.start()
        self.addCleanup(off_mac.stop)
        for v in ("0.1.0", "0.2.0", "0.10.0"):
            self.layout("iorlas-task-loop", v, "skills/task-loop/tl.py")
        self.record("iorlas-task-loop", "0.10.0")

    def layout(self, plugin, v, main):
        d = self.claude / "plugins" / "cache" / "iorlas-marketplace" / plugin / v
        (d / main).parent.mkdir(parents=True)
        (d / main).write_text("")
        return d

    def record(self, plugin, v):
        f = self.claude / "plugins" / "installed_plugins.json"
        recs = json.loads(f.read_text()) if f.exists() else {"version": 2, "plugins": {}}
        d = self.claude / "plugins" / "cache" / "iorlas-marketplace" / plugin / v
        recs["plugins"][f"{plugin}@iorlas-marketplace"] = [{"scope": "user", "installPath": str(d), "version": v}]
        f.write_text(json.dumps(recs))

    def pin(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            rc = tl.main(["pin", *args])
        return rc, out.getvalue(), err.getvalue()

    def pinned(self):
        return wire.dump(must(PinStore(homes.cfg()).get()))

    def test_pin_writes_version_and_clear_removes_the_file(self):
        rc, out, _ = self.pin("0.2.0")
        assert rc == 0, out
        pin = self.pinned()
        assert pin["task-loop"] == "0.2.0"
        assert "delegate" not in pin
        assert self.pin("--clear")[0] == 0
        assert PinStore(homes.cfg()).get() is None
        assert self.pin("--clear")[0] == 0  # clearing nothing is fine

    def test_a_pin_to_a_missing_cache_dir_is_refused_and_writes_nothing(self):
        rc, _, err = self.pin("0.3.0")
        assert rc == 2
        assert "0.3.0 is not installed" in err
        assert "0.1.0, 0.2.0, 0.10.0" in err
        assert PinStore(homes.cfg()).get() is None
        shutil.rmtree(self.claude / "plugins/cache/iorlas-marketplace/iorlas-task-loop/0.1.0/skills")  # half-copied
        assert self.pin("0.1.0")[0] == 2

    def test_rollback_pins_the_previous_version(self):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            assert tl.main(["rollback"]) == 0
        pin = self.pinned()
        assert pin["task-loop"] == "0.2.0"  # numbers: 0.2.0 comes before 0.10.0
        with mock.patch.object(sys, "stdout", out):
            assert tl.main(["rollback"]) == 0  # again: one step further back from the pin
        assert self.pinned()["task-loop"] == "0.1.0"
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", io.StringIO()):
            assert tl.main(["rollback"]) == 2  # nothing older
        assert self.pinned()["task-loop"] == "0.1.0"

    def test_the_drill_pin_decides_what_loop_picks_then_clear_returns_to_the_newest(self):
        assert self.pin("0.1.0")[0] == 0
        root = self.claude / "plugins/cache/iorlas-marketplace/iorlas-task-loop/0.2.0"
        def target(**kw):
            return wstart.installs(homes.cfg(), snapshot(), here=root / "skills" / "task-loop").target(**kw)
        assert target() == ("0.1.0", root.parent / "0.1.0")  # older than the running one: still the pin
        assert target(skip=["0.1.0"]) is None
        assert self.pin("--clear")[0] == 0
        assert target() == ("0.10.0", root.parent / "0.10.0")
        # the CLI end to end, main(argv) with only the scratch dirs in its environment
        cli = ["pin"]
        with mock.patch.object(pinning.sys, "platform", "linux"):  # the Mac devbox-ok rule reads origin: not what this test is about
            r = tl_main(*cli, "0.2.0", cwd=self.home, env={"HOME": str(self.home)})
            assert r.returncode == 0, r.stderr
            r = tl_main(*cli, "0.4.0", cwd=self.home, env={"HOME": str(self.home)})
        assert r.returncode == 2
        assert self.pinned()["task-loop"] == "0.2.0"



def test_pin_rejects_the_removed_delegate_option():
    err = io.StringIO()
    with mock.patch.object(sys, "stderr", err), pytest.raises(SystemExit) as stopped:
        tl.main(["pin", "--delegate", "0.5.0"])
    assert stopped.value.code == 2
    assert "unrecognized arguments: --delegate" in err.getvalue()


def ask_file(asks, bead, **over):
    """A current-version ask in the database, the way the engine files one."""
    base = wire.dump(S.ASK)
    rec = {**base, "id": bead + "-1", "bead": bead, "status": "open", "answer": None, "answered": None, "consumed": None, **over}
    asks.put(wire.load(Ask, rec))


class AskCli(Case):
    """tl ask: the inbox from the terminal. An answer is a typed record on the ask, never a comment."""

    def test_list_answer_and_withdraw(self):
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            asks = AskStore.at(ConfigDir(d / "task-loop"))
            for bead in ("x-1", "x-2"):
                ask_file(asks, bead, parks_at=9e12, repo=str(d), title="T " + bead)
            env = {"XDG_CONFIG_HOME": str(d), "APPDATA": str(d), "HOME": str(d), "USERPROFILE": str(d)}
            def ns(**k):
                return type("A", (), dict({"op": "list", "bead": None, "text": [], "json": False}, **k))()
            with mock.patch.dict(os.environ, env), tlbd.bd_boundary():
                out = io.StringIO()
                with mock.patch("sys.stdout", out):
                    c = ctx()
                    assert tl.v_ask(ns(), c) == 0
                    assert tl.v_ask(ns(op="answer", bead="x-1", text=["right"]), c) == 0
                    assert tl.v_ask(ns(op="withdraw", bead="x-2", text=["no", "longer"]), c) == 0
                    assert tl.v_ask(ns(op="answer", bead="nope", text=["x"]), c) == 1
                    assert tl.v_ask(ns(op="answer", bead="x-1", text=["again"]), c) == 1  # already answered
                    assert tl.v_ask(ns(op="answer", bead="x-1", text=["again"], amend=True), c) == 0
                assert "x-1" in out.getvalue()
                a = wire.dump(must(asks.of(BeadId("x-1")).get()))
                assert (a["status"], a["answer"]["action"], a["answer"]["text"]) == ("answered", "text", "again")
                a = wire.dump(must(asks.of(BeadId("x-2")).get()))
                assert (a["status"], a["closed_why"]) == ("withdrawn", "no longer")


class ParkStaleAsks(Case):
    """tl-bxk.8.25: an ask with no answer 3 days after it was asked is parked, once, with a comment; it still waits."""

    def test_parks_only_late_unanswered_open_asks(self):
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            asks = AskStore.at(ConfigDir(d / "task-loop"))
            now = time.time()
            done = {"status": "answered", "answered": now, "answer": {"action": "text", "text": "x", "t": now, "by": "denis"}}
            for bead, parks, extra in (("late", now - 10, {}), ("fresh", now + 9e4, {}), ("done", now - 10, done),
                                       ("closed", now - 10, {"status": "closed"})):
                ask_file(asks, bead, parks_at=parks, repo=str(d), **extra)
            env = {"XDG_CONFIG_HOME": str(d), "APPDATA": str(d), "HOME": str(d), "USERPROFILE": str(d)}
            with mock.patch.dict(os.environ, env), tlbd.bd_boundary() as bd_calls:
                assert wasks.sweep("park", who(), homes.cfg(), every=0) == ["late"]
                assert wasks.sweep("park", who(), homes.cfg(), every=600) == []  # throttled
            def status(b):
                return must(asks.of(b).get()).status.value
            assert [status(b) for b in ("late", "fresh", "done", "closed")] == ["parked", "open", "answered", "closed"]
            log = "\n".join(" ".join(c) for c in bd_calls.calls)
            assert "comments add late Parked (engine): ask late-1 got no answer in 3 days" in log
            assert log.count("comments add") == 1
