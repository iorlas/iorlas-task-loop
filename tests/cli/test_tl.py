"""The tl.py launcher: its verbs and output."""
import io
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401

# isort: split
import contextlib  # noqa: E402

import tl  # noqa: E402
from contracts import samples as S  # noqa: E402
from support import (  # noqa: E402
    looptest,
    procsim,
    tlbd,
)
from support.narrow import must  # noqa: E402
from support.procsim import real_proc  # noqa: E402
from support.tlmain import tl_main  # noqa: E402

from taskloop.adapters import delegate as lroute  # noqa: E402
from taskloop.adapters import (  # noqa: E402
    gitrepo,
    ident,
    pidcheck,
)
from taskloop.app.launch import loop as wloop  # noqa: E402
from taskloop.app.release import pins  # noqa: E402
from taskloop.app.slots import engine_lock  # noqa: E402
from taskloop.app.track import trail  # noqa: E402
from taskloop.app.wire import asks as wasks  # noqa: E402
from taskloop.app.wire import slots as wslots  # noqa: E402
from taskloop.contracts import wire  # noqa: E402

CTX = tl.Ctx(tl.HERE, trail.now, [])


def sh(*args, cwd):
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        env = {"XDG_CONFIG_HOME": str(self.home / "cfg"), "APPDATA": str(self.home / "cfg"),
               "CLAUDE_CODE_SESSION_ID": "abcdef12-3456", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        os.environ.pop("TASK_LOOP_ACTOR", None)

    def tearDown(self):
        self.env.stop()

        def force(fn, path, _):  # Windows: git's pack files are read-only
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        shutil.rmtree(self.tmp.name, onerror=force)
        with contextlib.suppress(OSError):
            self.tmp.cleanup()


class Identity(Base):
    def test_actor_is_per_session(self):
        self.assertEqual(ident.actor(), "tl-abcdef12")

    def test_actor_without_session_id_is_still_per_process(self):
        os.environ.pop("CLAUDE_CODE_SESSION_ID")
        os.environ["CLAUDE_PID"] = "4242"
        self.assertTrue(ident.actor().endswith("-4242"))

    def test_actor_override(self):
        os.environ["TASK_LOOP_ACTOR"] = "me"
        self.assertEqual(ident.actor(), "me")

    def test_config_dir_is_created(self):
        self.assertTrue(ident.config_dir().is_dir())


class Records(Base):
    def test_event_appends_and_registers_repo(self):
        trail.event("claim", "x-1", repo=str(self.home), worktree="/w")
        trail.event("close", "x-1", repo=str(self.home))
        lines = (ident.config_dir() / "events.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(ln)["kind"] for ln in lines], ["claim", "close"])
        self.assertEqual(json.loads(lines[0])["session"], "abcdef12-3456")
        self.assertIn(str(self.home), json.loads((ident.config_dir() / "repos.json").read_text()))

    @unittest.skipIf(os.name == "nt", "the registry lock is fcntl")
    def test_writers_registering_at_once_neither_crash_nor_lose_a_repo(self):
        # race test (tl-bxk.11.1): every process wrote repos.tmp; the second os.replace found it gone and the event
        # (a claim's, a slot take's) raised. Each writer now has its own tmp file, under a lock, so none is lost.
        errs = []

        def writer(n):
            try:
                for i in range(10):
                    trail.register_repo(f"/r/{n}-{i}")
            except Exception as e:
                errs.append(e)
        ps = [threading.Thread(target=writer, args=(n,)) for n in range(5)]  # the lock is on the open file: two descriptors conflict
        for p in ps:
            p.start()
        for p in ps:
            p.join(60)
        self.assertEqual(errs, [])
        repos = json.loads((ident.config_dir() / "repos.json").read_text())
        self.assertEqual(len(repos), 50)

    def test_prune_keeps_recent(self):
        f = ident.config_dir() / "events.jsonl"
        old = json.dumps({"t": 0, "kind": "old"})
        new = json.dumps({"t": trail.now(), "kind": "new"})
        f.write_text((old + "\n") * 120000 + new + "\n")
        trail.prune_events()
        self.assertEqual([json.loads(ln)["kind"] for ln in f.read_text().splitlines()], ["new"])


class RegisterCLI(Base):
    def setUp(self):
        super().setUp()
        self.repo = self.home / "repo"
        sh("git", "init", "-q", str(self.repo), cwd=self.home)
        self.config = self.home / "cfg" / "task-loop"
        self.registry = self.config / "repos.json"

    def cli(self, *args, cwd=None):
        return tl_main(*args, cwd=cwd or self.home)

    def assert_registered(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "REGISTERED " + str(self.repo.resolve()) + "\n")
        self.assertEqual(result.stderr, "")
        repos = json.loads(self.registry.read_text())
        self.assertIn(str(self.repo.resolve()), repos)
        self.assertIsInstance(repos[str(self.repo.resolve())]["added"], (int, float))

    def test_default_directory(self):
        self.assert_registered(self.cli("register", cwd=self.repo))
        self.assertEqual([p for p in self.config.iterdir() if p.name != "locks"], [self.registry])  # no tmp left

    def test_explicit_relative_subdirectory(self):
        (self.repo / "nested dir").mkdir()
        self.assert_registered(self.cli("register", "repo/nested dir"))

    def test_worktree_default_and_explicit_share_main_checkout(self):
        sh("git", "commit", "-qm", "init", "--allow-empty", cwd=self.repo)
        worktree = self.home / "linked"
        sh("git", "worktree", "add", "-q", "--detach", str(worktree), cwd=self.repo)
        self.assert_registered(self.cli("register", str(self.repo)))
        original = self.registry.read_bytes()
        self.assert_registered(self.cli("register", cwd=worktree))
        self.assert_registered(self.cli("register", str(worktree)))
        self.assertEqual(self.registry.read_bytes(), original)
        self.assertEqual(len(json.loads(original)), 1)

    def test_repeated_registration_preserves_entries_and_metadata(self):
        self.config.mkdir(parents=True)
        existing = {str(self.home / "other"): {"added": 123, "extra": "keep"}}
        self.registry.write_text(json.dumps(existing))
        self.assert_registered(self.cli("register", str(self.repo)))
        original = self.registry.read_bytes()
        self.assert_registered(self.cli("register", str(self.repo)))
        self.assertEqual(self.registry.read_bytes(), original)
        repos = json.loads(original)
        self.assertEqual(len(repos), 2)
        for path, metadata in existing.items():
            self.assertEqual(repos[path], metadata)

    def in_process(self, *args):
        out, err, cwd = io.StringIO(), io.StringIO(), os.getcwd()
        os.chdir(self.home)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = tl.main(list(args))
        finally:
            os.chdir(cwd)
        return rc, out.getvalue(), err.getvalue()

    def test_invalid_input_leaves_configuration_unchanged(self):
        ordinary = self.home / "ordinary"
        ordinary.mkdir()
        file = self.home / "file"
        file.write_text("not a directory")
        original = b""
        for configured in (False, True):
            if configured:
                self.config.mkdir(parents=True)
                self.registry.write_text('{"existing": {"added": 123}}\n')
                original = self.registry.read_bytes()
            cases = [("register",), ("register", str(ordinary)),
                     ("register", str(self.home / "missing")), ("register", str(file)),
                     ("register", str(self.home / "missing\nwith newline"))]
            for args in cases:
                with self.subTest(configured=configured, args=args):
                    rc, out, err = self.in_process(*args)
                    self.assertEqual(rc, 1)
                    self.assertEqual(out, "")
                    self.assertEqual(len(err.splitlines()), 1)
                    self.assertTrue(err.startswith("tl: "), err)
                    if configured:
                        self.assertEqual(self.registry.read_bytes(), original)
                        self.assertEqual([p for p in self.config.iterdir() if p.name != "locks"], [self.registry])  # no tmp left
                    else:
                        self.assertFalse(self.config.parent.exists())

    def test_invalid_input_exits_1_with_one_tl_line_on_stderr_and_no_traceback(self):
        result = self.cli("register", str(self.home / "missing"))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertTrue(result.stderr.startswith("tl: "), result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_help_documents_register_and_optional_directory(self):
        result = self.cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("register [DIR]", result.stdout)
        result = self.cli("register", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("[DIR]", result.stdout)
        self.assertIn("current directory", result.stdout)
        self.assertFalse(self.config.parent.exists())


class UsageCLI(Base):
    def test_usage_feeds_the_installed_delegate(self):
        d = self.home / ".claude/plugins/cache/iorlas-marketplace/iorlas-delegate/0.15.0/skills/delegate"
        d.mkdir(parents=True)
        (d / "route.py").write_text("")
        got = []

        def route(cwd, env):  # the delegate's route.py is a process by contract; here it is a fake that notes its argv
            got.append(list(procsim.argv()[2:]))
            return 0, json.dumps({"lanes": {"CLAUDE_SUBSCRIPTION": {"five": 6.0, "week": 4.0, "out": False}}})
        procsim.fake(shlex.join([sys.executable, str(d / "route.py")]), route, args=True)
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home))
        r = tl_main("usage", "[]", cwd=self.home, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("5h 6.0%, week 4.0%", r.stdout)
        self.assertEqual(got, [["status", "--claude-usage", "[]", "--json"]])


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
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("b-1-20261019-010000  b-1  landed  10 min", r.stdout)
        self.assertIn("thr-9", r.stdout)
        self.assertNotIn("b-2-x", r.stdout)


class SlotReset(Base):
    """A slot reset must never lose a dead session's work."""

    def setUp(self):
        super().setUp()
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

    def tearDown(self):
        os.chdir(self.cwd)
        super().tearDown()

    def reset(self, bead):
        return tl.main(["slot", "reset", "s1", "--bead", bead])

    def test_clean_reset_makes_task_branch_and_keeps_ignored(self):
        (self.slot / "ignored").mkdir()
        (self.slot / "ignored" / "big").write_text("setup output")
        (self.slot / "junk.tmp").write_text("x")
        sh("git", "add", "junk.tmp", cwd=self.slot)
        sh("git", "commit", "-qm", "junk", cwd=self.slot)  # committed work on a detached head is not our concern
        self.assertEqual(self.reset("t-1"), 0)
        self.assertEqual(gitrepo.git("symbolic-ref", "--short", "HEAD", cwd=str(self.slot)), "task/t-1")
        self.assertTrue((self.slot / "ignored" / "big").exists())

    def test_dirty_slot_work_is_committed_not_wiped(self):
        sh("git", "checkout", "-q", "-b", "task/t-0", cwd=self.slot)
        (self.slot / "a.txt").write_text("changed by a dead session\n")
        (self.slot / "new.txt").write_text("new\n")
        self.assertEqual(self.reset("t-1"), 0)
        self.assertEqual(gitrepo.git("status", "--porcelain", cwd=str(self.slot)), "")
        self.assertEqual(gitrepo.git("show", "task/t-0:new.txt", cwd=str(self.slot)), "new")
        self.assertEqual(gitrepo.git("show", "task/t-0:a.txt", cwd=str(self.slot)), "changed by a dead session")

    def test_reset_for_a_bead_keeps_its_existing_branch(self):
        sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.slot)
        (self.slot / "work.txt").write_text("reviewed work\n")
        sh("git", "add", "-A", cwd=self.slot)
        sh("git", "commit", "-qm", "wip (t-1): blocked", cwd=self.slot)
        sh("git", "checkout", "-q", "--detach", "origin/main", cwd=self.slot)
        self.assertEqual(self.reset("t-1"), 0)
        self.assertEqual(gitrepo.git("symbolic-ref", "--short", "HEAD", cwd=str(self.slot)), "task/t-1")
        self.assertEqual((self.slot / "work.txt").read_text(), "reviewed work\n")

    def test_loop_folders_are_excluded_from_git_add(self):
        wslots.exclude_local(str(self.repo), ".slots/", ".task/")
        wslots.exclude_local(str(self.repo), ".slots/")
        exclude = (self.repo / ".git" / "info" / "exclude").read_text()
        self.assertEqual(exclude.split().count(".slots/"), 1)
        self.assertNotIn(".slots", gitrepo.git("status", "--porcelain", "--untracked-files=all", cwd=str(self.repo)))

    def test_detached_dirty_work_goes_to_wip_branch(self):
        (self.slot / "new.txt").write_text("new\n")
        self.assertEqual(self.reset("t-2"), 0)
        wip = [b for b in gitrepo.git("branch", "--list", "wip/*", cwd=str(self.slot)).split() if b.startswith("wip/")]
        self.assertEqual(len(wip), 1)
        self.assertEqual(gitrepo.git("show", wip[0] + ":new.txt", cwd=str(self.slot)), "new")

    def test_setup_runs_only_when_inputs_change(self):
        cfg = {
            "slots": {
                "count": 1,
                "setup": ["sh", "-c", "echo run >> setup.log"],
                "setup_inputs": ["a.txt"],
                "keep": ["setup.log"],
            }
        }
        def setup(cwd, env):
            with (cwd / "setup.log").open("a") as f:
                f.write("run\n")
            return 0, ""
        procsim.fake("sh -c 'echo run >> setup.log'", setup)
        (self.repo / ".task-loop.json").write_text(json.dumps(cfg))
        (self.slot / ".gitignore").write_text("ignored/\nsetup.log\n")
        sh("git", "add", "-A", cwd=self.slot)
        sh("git", "commit", "-qm", "ignore log", cwd=self.slot)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.slot)
        self.assertEqual(self.reset("t-1"), 0)
        self.assertEqual(self.reset("t-2"), 0)
        self.assertEqual((self.slot / "setup.log").read_text().count("run"), 1)


class PinAndRollback(Base):
    """pinned.json and the verbs that write it, against a scratch CLAUDE_CONFIG_DIR laid out as the plugin cache is."""

    def setUp(self):
        super().setUp()
        self.claude = self.home / "claude"
        p = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.claude)})
        p.start()
        self.addCleanup(p.stop)
        for v in ("0.1.0", "0.2.0", "0.10.0"):
            self.layout("iorlas-task-loop", v, "skills/task-loop/tl.py")
        for v in ("0.5.0", "0.6.0"):
            self.layout("iorlas-delegate", v, "skills/delegate/route.py")
        self.record("iorlas-task-loop", "0.10.0")
        self.record("iorlas-delegate", "0.6.0")

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
        return json.loads((ident.config_dir() / "pinned.json").read_text())

    def test_pin_writes_both_versions_and_clear_removes_the_file(self):
        rc, out, _ = self.pin("0.2.0", "--delegate", "0.5.0")
        self.assertEqual(rc, 0, out)
        pin = self.pinned()
        self.assertEqual((pin["task-loop"], pin["delegate"]), ("0.2.0", "0.5.0"))
        self.assertEqual(self.pin("--delegate", "0.6.0")[0], 0)  # one side only: the other stays
        self.assertEqual((self.pinned()["task-loop"], self.pinned()["delegate"]), ("0.2.0", "0.6.0"))
        self.assertEqual(self.pin("--clear")[0], 0)
        self.assertFalse((ident.config_dir() / "pinned.json").exists())
        self.assertEqual(self.pin("--clear")[0], 0)  # clearing nothing is fine

    def test_a_pin_to_a_missing_cache_dir_is_refused_and_writes_nothing(self):
        rc, _, err = self.pin("0.3.0")
        self.assertEqual(rc, 2)
        self.assertIn("0.3.0 is not installed", err)
        self.assertIn("0.1.0, 0.2.0, 0.10.0", err)
        self.assertEqual(self.pin("0.2.0", "--delegate", "9.9.9")[0], 2)
        self.assertFalse((ident.config_dir() / "pinned.json").exists())  # not even the valid half
        shutil.rmtree(self.claude / "plugins/cache/iorlas-marketplace/iorlas-task-loop/0.1.0/skills")  # half-copied
        self.assertEqual(self.pin("0.1.0")[0], 2)

    def test_rollback_pins_the_previous_version_and_keeps_the_installed_delegate(self):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            self.assertEqual(tl.main(["rollback"]), 0)
        pin = self.pinned()
        self.assertEqual((pin["task-loop"], pin["delegate"]), ("0.2.0", "0.6.0"))  # numbers: 0.2.0 comes before 0.10.0
        with mock.patch.object(sys, "stdout", out):
            self.assertEqual(tl.main(["rollback"]), 0)  # again: one step further back from the pin
        self.assertEqual(self.pinned()["task-loop"], "0.1.0")
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", io.StringIO()):
            self.assertEqual(tl.main(["rollback"]), 2)  # nothing older
        self.assertEqual(self.pinned()["task-loop"], "0.1.0")

    def test_find_route_follows_the_pin_then_the_installed_entry_not_the_newest_directory(self):
        self.record("iorlas-delegate", "0.5.0")  # the plugin manager installed 0.5.0; 0.6.0 is only a directory
        def route():
            return lroute.find_route("", pins.pinned_dir("delegate"), ident.claude_dir() / "plugins" / "cache",
                                                  lroute.installed_dir(ident.claude_dir()))
        self.assertIn("/iorlas-delegate/0.5.0/", must(route()))
        self.assertEqual(self.pin("0.1.0", "--delegate", "0.6.0")[0], 0)
        self.assertIn("/iorlas-delegate/0.6.0/", must(route()))

    def test_the_drill_pin_decides_what_loop_and_find_route_pick_then_clear_returns_to_the_newest(self):

        def route():
            return lroute.find_route("", pins.pinned_dir("delegate"), ident.claude_dir() / "plugins" / "cache")
        self.assertIn("0.6.0", must(route()))  # no pin: the newest
        self.assertEqual(self.pin("0.1.0", "--delegate", "0.5.0")[0], 0)
        self.assertIn("/iorlas-delegate/0.5.0/", must(route()))
        root = self.claude / "plugins/cache/iorlas-marketplace/iorlas-task-loop/0.2.0"
        def target(**kw):
            return wloop.installs(wloop.cfgdir(), here=root / "skills" / "task-loop").target(**kw)
        self.assertEqual(target(), ("0.1.0", root.parent / "0.1.0"))  # older than the running one: still the pin
        self.assertEqual(target(skip=["0.1.0"]), None)
        self.assertEqual(self.pin("--clear")[0], 0)
        self.assertEqual(target(), ("0.10.0", root.parent / "0.10.0"))
        self.assertIn("0.6.0", must(route()))
        # the CLI end to end, main(argv) with only the scratch dirs in its environment
        cli = ["pin"]
        r = tl_main(*cli, "0.2.0", "--delegate", "0.5.0", cwd=self.home, env={"HOME": str(self.home)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("/iorlas-delegate/0.5.0/", must(route()))
        r = tl_main(*cli, "0.4.0", cwd=self.home, env={"HOME": str(self.home)})
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.pinned()["task-loop"], "0.2.0")


@unittest.skipIf(os.name == "nt", "the fixture's live process is a POSIX ps lookup")
class CutoverCheck(Base):
    def setUp(self):
        super().setUp()
        self.repo = self.home / "repo"
        self.repo.mkdir()
        sh("git", "init", "-q", cwd=self.repo)
        trail.register_repo(str(self.repo))
        p = mock.patch.object(wslots, "slot_beads", return_value=[])
        p.start()
        self.addCleanup(p.stop)

    def check(self, *args):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = tl.main(["cutover", "check", *args])
        return rc, out.getvalue()

    def test_nothing_live_exits_0(self):
        rc, out = self.check()
        self.assertEqual((rc, out.split()[0]), (0, "CLEAR:"))

    @real_proc("a live pid (a sleeping child), then a dead one: what cutover check reads off the process table")
    def test_a_live_loop_and_a_live_run_exit_1_and_are_listed_a_dead_one_is_not(self):
        child = subprocess.Popen(["sleep", "60"])
        self.addCleanup(child.wait)  # cleanups run last-in first-out: kill, then wait
        self.addCleanup(child.kill)
        looptest.write_state(str(self.repo), pid=child.pid, started=time.time(), t=time.time(), bead="x-9")
        engine_lock.write_engine_lock(str(self.repo), {"pid": child.pid, "start": pidcheck.proc_start(child.pid), "bead": "x-7",
                                              "by": "engine", "started": time.time()})
        rc, out = self.check()
        self.assertEqual(rc, 1, out)
        self.assertIn(f"LIVE loop pid {child.pid} on {self.repo} running x-9", out)
        self.assertIn(f"LIVE run in {self.repo}: engine pid {child.pid} runs x-7", out)
        rc, out = self.check("--json")
        self.assertEqual((rc, sorted(x["kind"] for x in json.loads(out)["live"])), (1, ["loop", "run"]))
        child.kill()
        child.wait()
        self.assertEqual(self.check()[0], 0)


if __name__ == "__main__":
    unittest.main()


def ask_file(asks, bead, **over):
    """A current-version ask record on disk, the way the engine files one."""
    base = wire.dump(S.ASK)
    rec = {**base, "id": bead + "-1", "bead": bead, "status": "open", "answer": None, "answered": None, "consumed": None, **over}
    (asks / (f"{bead}.json")).write_text(json.dumps(rec))


class AskCli(unittest.TestCase):
    """tl ask: the inbox from the terminal. An answer is a typed record on the ask, never a comment."""

    def test_list_answer_and_withdraw(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            asks = d / "task-loop" / "asks"
            asks.mkdir(parents=True)
            for bead in ("x-1", "x-2"):
                ask_file(asks, bead, parks_at=9e12, repo=str(d), title="T " + bead)
            env = {"XDG_CONFIG_HOME": str(d), "APPDATA": str(d), "HOME": str(d), "USERPROFILE": str(d)}
            def ns(**k):
                return type("A", (), dict({"op": "list", "bead": None, "text": [], "json": False}, **k))()
            with mock.patch.dict(os.environ, env), tlbd.bd_boundary():
                out = io.StringIO()
                with mock.patch("sys.stdout", out):
                    self.assertEqual(tl.v_ask(ns(), CTX), 0)
                    self.assertEqual(tl.v_ask(ns(op="answer", bead="x-1", text=["right"]), CTX), 0)
                    self.assertEqual(tl.v_ask(ns(op="withdraw", bead="x-2", text=["no", "longer"]), CTX), 0)
                    self.assertEqual(tl.v_ask(ns(op="answer", bead="nope", text=["x"]), CTX), 1)
                    self.assertEqual(tl.v_ask(ns(op="answer", bead="x-1", text=["again"]), CTX), 1)  # already answered
                    self.assertEqual(tl.v_ask(ns(op="answer", bead="x-1", text=["again"], amend=True), CTX), 0)
                self.assertIn("x-1", out.getvalue())
                a = json.loads((asks / "x-1.json").read_text())
                self.assertEqual((a["status"], a["answer"]["action"], a["answer"]["text"]), ("answered", "text", "again"))
                a = json.loads((asks / "x-2.json").read_text())
                self.assertEqual((a["status"], a["closed_why"]), ("withdrawn", "no longer"))


class ParkStaleAsks(unittest.TestCase):
    """tl-bxk.8.25: an ask with no answer 3 days after it was asked is parked, once, with a comment; it still waits."""

    def test_parks_only_late_unanswered_open_asks(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            asks = d / "task-loop" / "asks"
            asks.mkdir(parents=True)
            now = time.time()
            done = {"status": "answered", "answered": now, "answer": {"action": "text", "text": "x", "t": now, "by": "denis"}}
            for bead, parks, extra in (("late", now - 10, {}), ("fresh", now + 9e4, {}), ("done", now - 10, done),
                                       ("closed", now - 10, {"status": "closed"})):
                ask_file(asks, bead, parks_at=parks, repo=str(d), **extra)
            env = {"XDG_CONFIG_HOME": str(d), "APPDATA": str(d), "HOME": str(d), "USERPROFILE": str(d)}
            with mock.patch.dict(os.environ, env), tlbd.bd_boundary() as bd_calls:
                self.assertEqual(wasks.sweep("park", every=0), ["late"])
                self.assertEqual(wasks.sweep("park", every=600), [])  # throttled
            def status(b):
                return json.loads((asks / (f"{b}.json")).read_text())["status"]
            self.assertEqual([status(b) for b in ("late", "fresh", "done", "closed")], ["parked", "open", "answered", "closed"])
            log = "\n".join(" ".join(c) for c in bd_calls.calls)
            self.assertIn("comments add late Parked (engine): ask late-1 got no answer in 3 days", log)
            self.assertEqual(log.count("comments add"), 1)
