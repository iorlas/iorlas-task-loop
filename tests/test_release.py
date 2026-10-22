"""dev/release.py against a fake remote: bare git repos in a temp dir, the claude and bd CLIs faked on PATH."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "dev" / "release.py"
PLUGIN = ".claude-plugin/plugin.json"
MARKET = ".claude-plugin/marketplace.json"


def sh(*a, cwd):
    return subprocess.run(list(a), cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipIf(os.name == "nt", "fake CLIs are shell scripts; the lock is fcntl")
class Release(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        h = self.home = Path(self.tmp.name)
        shim = h / "bin"
        shim.mkdir()
        for name in ("claude", "bd"):
            f = shim / name
            f.write_text('#!/bin/sh\necho "$@" >> "%s"\n' % (h / (name + ".log")))
            f.chmod(0o755)
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(h / "cfg"), PATH="%s%s%s" % (shim, os.pathsep, os.environ["PATH"]),
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            self.env.pop(k, None)
        self.origin, self.seed, self.repo = h / "o.git", h / "seed", h / "repo"
        self.morigin, self.market = h / "m.git", h / "market"
        self.git("init", "-q", "--bare", "-b", "main", str(self.origin), cwd=h)
        self.git("clone", "-q", str(self.origin), str(self.seed), cwd=h)
        self.git("checkout", "-q", "-B", "main", cwd=self.seed)  # an empty clone's branch follows init.defaultBranch
        self.write(self.seed / PLUGIN, json.dumps({"name": "iorlas-task-loop", "version": "0.1.0",
                                                   "author": {"name": "t"}}, indent=2) + "\n")
        self.write(self.seed / "tests" / "test_ok.py", "import time\nimport unittest\n\n\nclass T(unittest.TestCase):\n"
                                                        "    def test_ok(self):\n        time.sleep(1)\n")
        self.commit(self.seed, "init")
        self.git("clone", "-q", str(self.origin), str(self.repo), cwd=h)
        self.git("init", "-q", "--bare", "-b", "main", str(self.morigin), cwd=h)
        self.git("clone", "-q", str(self.morigin), str(self.market), cwd=h)
        self.git("checkout", "-q", "-B", "main", cwd=self.market)
        self.write(self.market / MARKET, json.dumps({"name": "iorlas-marketplace", "plugins": [
            {"name": "other", "source": "./other", "version": "0.1.0"},
            {"name": "iorlas-task-loop", "source": "x", "version": "0.1.0"}]}, indent=2) + "\n")
        self.commit(self.market, "init")

    def tearDown(self):
        def force(fn, path, _):
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        shutil.rmtree(self.tmp.name, onerror=force)
        try:
            self.tmp.cleanup()
        except OSError:
            pass

    def git(self, *a, cwd):
        return subprocess.run(["git"] + list(a), cwd=cwd, env=self.env, check=True, capture_output=True,
                              text=True).stdout.strip()

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, wt, msg):
        self.git("add", "-A", cwd=wt)
        self.git("commit", "-qm", msg, cwd=wt)
        self.git("push", "-q", "origin", "HEAD:main", cwd=wt)

    def cmd(self, *args):
        return [sys.executable, str(RELEASE)] + list(args) + ["--repo", str(self.repo), "--marketplace", str(self.market)]

    def release(self, *args):
        return subprocess.run(self.cmd(*args), env=self.env, capture_output=True, text=True, timeout=120)

    def version(self, bare, path=PLUGIN):
        return json.loads(self.git("show", "main:" + path, cwd=bare))

    def market_versions(self):
        return {p["name"]: p["version"] for p in self.version(self.morigin, MARKET)["plugins"]}

    def log(self, name):
        f = self.home / (name + ".log")
        return f.read_text().splitlines() if f.exists() else []

    def test_two_releases_started_together_both_land_one_after_the_other_with_distinct_versions(self):
        procs = [subprocess.Popen(self.cmd(msg), env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True) for msg in ("first fix", "second fix")]
        outs = [p.communicate(timeout=120)[0] for p in procs]
        self.assertEqual([p.returncode for p in procs], [0, 0], outs)
        subjects = self.git("log", "--format=%s", "-2", "main", cwd=self.origin).splitlines()
        self.assertEqual(sorted(s.split(":")[0] for s in subjects), ["0.1.1", "0.1.2"])
        self.assertEqual({s.split(": ", 1)[1] for s in subjects}, {"first fix", "second fix"})
        self.assertEqual(self.version(self.origin)["version"], "0.1.2")
        self.assertEqual(self.market_versions(), {"other": "0.1.0", "iorlas-task-loop": "0.1.2"})
        waited = [o for o in outs if "waiting for the release lock" in o]
        self.assertEqual(len(waited), 1, outs)
        self.assertIn("held by", waited[0])
        self.assertRegex(waited[0], r"held by pid \d+")
        installs = [x for x in self.log("claude") if x == "plugin update iorlas-task-loop@iorlas-marketplace"]
        self.assertEqual(len(installs), 2)
        self.assertEqual(self.log("claude").count("plugin marketplace update iorlas-marketplace"), 2)
        self.assertEqual(self.git("status", "--porcelain", cwd=self.repo), "")

    def test_a_dirty_main_checkout_is_refused_before_anything_moves(self):
        (self.repo / "stray.txt").write_text("x")
        r = self.release("fix")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("dirty", r.stderr)
        self.assertEqual(self.version(self.origin)["version"], "0.1.0")
        self.assertEqual(self.log("claude"), [])

    def test_a_red_suite_aborts_and_leaves_main_where_it_was(self):
        start = self.git("rev-parse", "HEAD", cwd=self.repo)
        self.git("checkout", "-q", "-b", "task/x", cwd=self.repo)
        self.write(self.repo / "tests" / "test_red.py", "import unittest\n\n\nclass R(unittest.TestCase):\n"
                                                        "    def test_red(self):\n        self.fail('red')\n")
        self.git("add", "-A", cwd=self.repo)
        self.git("commit", "-qm", "broken", cwd=self.repo)
        self.git("checkout", "-q", "main", cwd=self.repo)
        r = self.release("fix", "--from-branch", "task/x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("suite", r.stderr)
        self.assertEqual(self.version(self.origin)["version"], "0.1.0")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.repo), start)
        self.assertEqual(self.git("status", "--porcelain", cwd=self.repo), "")
        self.assertEqual(self.market_versions()["iorlas-task-loop"], "0.1.0")
        self.assertEqual(self.log("claude"), [])

    def test_the_version_comes_from_origin_and_the_branch_lands_fast_forward(self):
        bumped = json.loads((self.seed / PLUGIN).read_text())
        bumped["version"] = "0.1.5"
        self.write(self.seed / PLUGIN, json.dumps(bumped, indent=2) + "\n")
        self.commit(self.seed, "0.1.5: elsewhere")  # the main checkout is not pulled: its plugin.json says 0.1.0
        self.git("fetch", "-q", "origin", cwd=self.repo)
        self.git("checkout", "-q", "-b", "task/y", "origin/main", cwd=self.repo)
        (self.repo / "feature.txt").write_text("y\n")
        self.git("add", "-A", cwd=self.repo)
        self.git("commit", "-qm", "Add feature (tl-1)", cwd=self.repo)
        self.git("checkout", "-q", "main", cwd=self.repo)
        r = self.release("feature", "--from-branch", "task/y", "--bead", "tl-1", "--reason", "landed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.version(self.origin)["version"], "0.1.6")
        self.assertEqual(self.git("log", "--format=%s", "-2", "main", cwd=self.origin).splitlines(),
                         ["0.1.6: feature", "Add feature (tl-1)"])
        self.assertIn("Co-Authored-By: Claude", self.git("log", "-1", "--format=%B", "main", cwd=self.origin))
        self.assertEqual(self.log("bd"), ["close tl-1 --reason landed"])
        self.assertEqual(self.market_versions()["iorlas-task-loop"], "0.1.6")
        self.assertEqual(json.loads((self.repo / PLUGIN).read_text())["author"], {"name": "t"})  # the rest kept

    def test_a_branch_that_is_not_a_fast_forward_is_refused(self):
        self.git("checkout", "-q", "-b", "task/z", cwd=self.repo)
        (self.repo / "z.txt").write_text("z\n")
        self.git("add", "-A", cwd=self.repo)
        self.git("commit", "-qm", "z", cwd=self.repo)
        self.git("checkout", "-q", "main", cwd=self.repo)
        (self.seed / "other.txt").write_text("o\n")
        self.commit(self.seed, "moved on")
        r = self.release("z", "--from-branch", "task/z")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("rebase task/z onto origin/main", r.stderr)
        self.assertEqual(self.version(self.origin)["version"], "0.1.0")

    def test_minor_bumps_the_minor_and_resets_the_patch(self):
        r = self.release("new feature", "--minor")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.version(self.origin)["version"], "0.2.0")

    def test_a_push_race_rebases_reruns_the_suite_and_takes_the_next_version(self):
        # another release lands between our fetch and our push: simulated by a pre-push hook that pushes once
        hook = self.repo / ".git" / "hooks" / "pre-push"
        hook.write_text("#!/bin/sh\nunset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE\n[ -f '%s' ] && exit 0\ntouch '%s'\ncd '%s' && sed -i.bak 's/0.1.0/0.1.1/' %s "
                        "&& rm %s.bak && git commit -qam '0.1.1: racer' && git push -q origin HEAD:main\n"
                        % (self.home / "raced", self.home / "raced", self.seed, PLUGIN, PLUGIN))
        hook.chmod(0o755)
        r = self.release("mine")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("push race", r.stdout)
        self.assertEqual(self.git("log", "--format=%s", "-2", "main", cwd=self.origin).splitlines(),
                         ["0.1.2: mine", "0.1.1: racer"])
        self.assertEqual(self.market_versions()["iorlas-task-loop"], "0.1.2")

    def test_a_red_suite_prints_each_failing_test_and_saves_the_full_output_outside_the_repo(self):
        self.write(self.seed / "tests" / "test_red.py", "import unittest\n\n\nclass R(unittest.TestCase):\n"
                                                        "    def test_red_one(self):\n        self.fail('boom')\n"
                                                        "    def test_red_two(self):\n        raise ValueError('bang')\n")
        self.commit(self.seed, "red")
        self.git("pull", "-q", "origin", "main", cwd=self.repo)
        r = self.release("fix")
        self.assertNotEqual(r.returncode, 0)
        for want in ("FAIL: test_red_one", "ERROR: test_red_two", "AssertionError: boom", "ValueError: bang",
                     "Ran 3 tests", "FAILED (failures=1, errors=1)"):
            self.assertIn(want, r.stderr)
        m = re.search(r"full output: (\S+)", r.stderr)
        self.assertTrue(m, r.stderr)
        saved = Path(m.group(1))
        self.assertIn(str(self.home / "cfg" / "task-loop" / "releases"), str(saved))
        self.assertIn("FAIL: test_red_one", saved.read_text())
        self.assertEqual(self.git("status", "--porcelain", cwd=self.repo), "")

    def test_failure_report_keeps_every_fail_and_error_section_and_the_summary_lines(self):
        sys.path.insert(0, str(ROOT / "dev"))
        import release
        out = textwrap.dedent("""\
            ..E.F.
            ======================================================================
            ERROR: test_a (tests.test_x.X.test_a)
            ----------------------------------------------------------------------
            Traceback (most recent call last):
              File "x.py", line 1, in test_a
            ValueError: bang

            ======================================================================
            FAIL: test_b (tests.test_x.X.test_b)
            ----------------------------------------------------------------------
            Traceback (most recent call last):
            AssertionError: 1 != 2

            ----------------------------------------------------------------------
            Ran 6 tests in 0.010s

            FAILED (failures=1, errors=1)
            sys:1: ResourceWarning: unclosed file
            """)
        rep = release.failure_report(out)
        self.assertIn("ERROR: test_a", rep)
        self.assertIn("ValueError: bang", rep)
        self.assertIn("FAIL: test_b", rep)
        self.assertIn("AssertionError: 1 != 2", rep)
        self.assertIn("Ran 6 tests in 0.010s", rep)
        self.assertIn("FAILED (failures=1, errors=1)", rep)
        self.assertNotIn("ResourceWarning", rep)
        self.assertNotIn("..E.F.", rep)

    def test_a_loop_landing_during_every_suite_run_never_fails_the_release(self):
        # race test (tl-bxk.11.1): loops land on the same origin; each lands when the land lock is free. A land during
        # the suite moved origin/main, the retry's suite saw another land, and the release aborted. The release now
        # pushes under the land lock: after the first suite no land gets in between its rebase, suite and push.
        import hashlib
        lock = self.home / "cfg" / "task-loop" / "locks" / (
            "land-%s.lock" % hashlib.sha1(str(self.origin).encode()).hexdigest()[:12])
        self.write(self.seed / "tests" / "test_land.py", textwrap.dedent('''
            import fcntl, os, subprocess, time, unittest
            LOCK, SIDE = %r, %r

            class Land(unittest.TestCase):
                def test_a_loop_lands_meanwhile(self):  # what an engine does at land, the lock taken as it takes it
                    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
                    with open(LOCK, "a+") as f:
                        try:
                            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except OSError:
                            return  # a land would wait here
                        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_DIR")}
                        run = lambda *a: subprocess.run(a, cwd=SIDE, env=env, check=True, capture_output=True)
                        run("git", "pull", "-q", "--rebase", "origin", "main")
                        name = "land-%%s.txt" %% time.time_ns()
                        open(os.path.join(SIDE, name), "w").write("x")
                        run("git", "add", name)
                        run("git", "commit", "-qm", "a bead (x-%%s)" %% name)
                        run("git", "push", "-q", "origin", "HEAD:main")
            ''' % (str(lock), str(self.home / "side"))))
        self.commit(self.seed, "a suite that sees a loop land")
        self.git("clone", "-q", str(self.origin), str(self.home / "side"), cwd=self.home)
        self.git("pull", "-q", "origin", "main", cwd=self.repo)
        r = self.release("mine")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        subjects = self.git("log", "--format=%s", "main", cwd=self.origin).splitlines()
        self.assertEqual(subjects[0], "0.1.1: mine")
        self.assertTrue(any(s.startswith("a bead") for s in subjects), subjects)
        self.assertEqual(self.git("rev-list", "--merges", "main", cwd=self.origin), "")


if __name__ == "__main__":
    unittest.main()
