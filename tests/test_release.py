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
import time
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
        self.write(self.seed / ".gitignore", "__pycache__/\n")  # the real repo ignores it; the inner suite writes it when bytecode is on
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

    def test_a_stale_branch_is_rebased_before_the_suite(self):
        for remote_only in (False, True):
            with self.subTest(remote_only=remote_only):
                name = "task/remote" if remote_only else "task/local"
                self.git("checkout", "-q", "-b", name, cwd=self.repo)
                self.write(self.repo / "z.txt", name + "\n")
                self.git("add", "-A", cwd=self.repo)
                self.git("commit", "-qm", name, cwd=self.repo)
                source = self.git("rev-parse", "HEAD", cwd=self.repo)
                self.git("checkout", "-q", "main", cwd=self.repo)
                if remote_only:
                    self.git("push", "-q", "origin", name, cwd=self.repo)
                    self.git("branch", "-D", name, cwd=self.repo)
                else:
                    worktree = self.home / "source-worktree"
                    self.git("worktree", "add", "-q", str(worktree), name, cwd=self.repo)
                self.git("pull", "-q", "--ff-only", "origin", "main", cwd=self.seed)
                self.write(self.seed / "other.txt", name + "\n")
                self.write(self.seed / "tests" / "test_rebased.py", textwrap.dedent('''
                    import unittest
                    from pathlib import Path
                    class Rebased(unittest.TestCase):
                        def test_both_changes_are_present(self):
                            self.assertEqual(Path("z.txt").read_text(), %r)
                            self.assertEqual(Path("other.txt").read_text(), %r)
                ''' % (name + "\n", name + "\n")))
                self.commit(self.seed, "moved on")
                r = self.release("z", "--from-branch", name)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(r.stdout.count("running the full suite"), 1)
                ref = "origin/" + name if remote_only else name
                self.assertEqual(self.git("rev-parse", ref, cwd=self.repo), source)
                if not remote_only:
                    self.assertEqual(self.git("rev-parse", "HEAD", cwd=worktree), source)
                    self.assertEqual(self.git("status", "--porcelain", cwd=worktree), "")
                self.assertEqual(self.git("show", "main:z.txt", cwd=self.origin), name)
                self.assertEqual(self.git("show", "main:other.txt", cwd=self.origin), name)
                self.assertEqual(self.git("rev-list", "--merges", "main", cwd=self.origin), "")

    def test_source_refs_survive_rebase_with_update_refs_enabled(self):
        self.git("config", "rebase.updateRefs", "true", cwd=self.repo)
        for suite_fails in (False, True):
            with self.subTest(suite_fails=suite_fails):
                name = "task/red" if suite_fails else "task/green"
                self.git("checkout", "-q", "-b", name, cwd=self.repo)
                self.write(self.repo / "feature.txt", name + "\n")
                if suite_fails:
                    self.write(self.repo / "tests" / "test_red.py", textwrap.dedent('''
                        import unittest
                        class Red(unittest.TestCase):
                            def test_red(self):
                                self.fail("red after rebase")
                    '''))
                self.git("add", "-A", cwd=self.repo)
                self.git("commit", "-qm", name, cwd=self.repo)
                source = self.git("rev-parse", "HEAD", cwd=self.repo)
                self.git("checkout", "-q", "main", cwd=self.repo)
                start = self.git("rev-parse", "HEAD", cwd=self.repo)
                self.git("pull", "-q", "--ff-only", "origin", "main", cwd=self.seed)
                self.write(self.seed / "other.txt", name + "\n")
                self.commit(self.seed, "advance main before " + name)
                origin = self.git("rev-parse", "main", cwd=self.origin)

                r = self.release(name, "--from-branch", name)

                self.assertEqual(self.git("rev-parse", name, cwd=self.repo), source, r.stdout + r.stderr)
                self.assertEqual(self.git("config", "--get", "rebase.updateRefs", cwd=self.repo), "true")
                self.assertEqual(self.git("branch", "--show-current", cwd=self.repo), "main")
                self.assertEqual(self.git("status", "--porcelain", cwd=self.repo), "")
                if suite_fails:
                    self.assertNotEqual(r.returncode, 0)
                    self.assertIn("red after rebase", r.stderr)
                    self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.repo), start)
                    self.assertEqual(self.git("rev-parse", "main", cwd=self.origin), origin)
                else:
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertEqual(self.git("show", "main:feature.txt", cwd=self.origin), name)
                    self.assertEqual(self.git("show", "main:other.txt", cwd=self.origin), name)

    def test_unpublished_main_commits_absent_from_the_branch_are_refused(self):
        self.git("checkout", "-q", "-b", "task/sibling", cwd=self.repo)
        self.write(self.repo / "sibling.txt", "branch change\n")
        self.git("add", "-A", cwd=self.repo)
        self.git("commit", "-qm", "sibling change", cwd=self.repo)
        source = self.git("rev-parse", "HEAD", cwd=self.repo)
        self.git("checkout", "-q", "main", cwd=self.repo)
        self.write(self.repo / "unpublished.txt", "keep this main commit\n")
        self.git("add", "-A", cwd=self.repo)
        self.git("commit", "-qm", "unpublished main change", cwd=self.repo)
        start = self.git("rev-parse", "HEAD", cwd=self.repo)
        origin = self.git("rev-parse", "main", cwd=self.origin)
        marketplace = self.git("rev-parse", "main", cwd=self.morigin)

        r = self.release("sibling", "--from-branch", "task/sibling")

        self.assertNotEqual(r.returncode, 0)
        self.assertIn("main has unpublished commits absent from task/sibling", r.stderr)
        self.assertNotIn("running the full suite", r.stdout)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.repo), start)
        self.assertEqual(self.git("branch", "--show-current", cwd=self.repo), "main")
        self.assertEqual(self.git("status", "--porcelain", cwd=self.repo), "")
        self.assertEqual((self.repo / "unpublished.txt").read_text(), "keep this main commit\n")
        self.assertFalse((self.repo / "sibling.txt").exists())
        self.assertEqual(self.git("rev-parse", "task/sibling", cwd=self.repo), source)
        self.assertEqual(self.git("rev-parse", "main", cwd=self.origin), origin)
        self.assertEqual(self.git("rev-parse", "main", cwd=self.morigin), marketplace)
        self.assertEqual(self.log("claude"), [])
        self.assertEqual(self.log("bd"), [])

    def test_a_rebase_conflict_aborts_and_restores_main(self):
        start = self.git("rev-parse", "HEAD", cwd=self.repo)
        self.git("checkout", "-q", "-b", "task/conflict", cwd=self.repo)
        self.write(self.repo / "conflict.txt", "branch\n")
        self.git("add", "-A", cwd=self.repo)
        self.git("commit", "-qm", "branch change", cwd=self.repo)
        source = self.git("rev-parse", "HEAD", cwd=self.repo)
        self.git("checkout", "-q", "main", cwd=self.repo)
        self.write(self.seed / "conflict.txt", "origin\n")
        self.commit(self.seed, "conflicting change")
        origin = self.git("rev-parse", "main", cwd=self.origin)
        r = self.release("conflict", "--from-branch", "task/conflict")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("rebase", r.stderr)
        self.assertNotIn("running the full suite", r.stdout)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.repo), start)
        self.assertEqual(self.git("branch", "--show-current", cwd=self.repo), "main")
        self.assertEqual(self.git("status", "--porcelain", cwd=self.repo), "")
        self.assertEqual(self.git("rev-parse", "task/conflict", cwd=self.repo), source)
        self.assertEqual(self.git("rev-parse", "main", cwd=self.origin), origin)
        self.assertFalse((self.repo / ".git" / "rebase-merge").exists())
        self.assertFalse((self.repo / ".git" / "rebase-apply").exists())
        self.assertEqual(self.market_versions()["iorlas-task-loop"], "0.1.0")
        self.assertEqual(self.log("claude"), [])

    def test_two_branch_releases_queue_rebase_and_test_the_pushed_tree(self):
        ready, proceed = self.home / "ready", self.home / "proceed"
        snapshots = self.home / "snapshots"
        snapshots.mkdir()
        self.write(self.seed / "tests" / "test_queue.py", textwrap.dedent('''
            import json, subprocess, time, unittest
            from pathlib import Path
            READY, PROCEED, SNAPSHOTS = Path(%r), Path(%r), Path(%r)
            class Queue(unittest.TestCase):
                def test_snapshot(self):
                    version = json.loads(Path(%r).read_text())["version"]
                    paths = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
                    snapshot = {p: Path(p).read_bytes().hex() for p in paths}
                    with (SNAPSHOTS / (version + ".jsonl")).open("a") as out:
                        out.write(json.dumps(snapshot) + "\\n")
                    if version == "0.1.1":
                        READY.touch()
                        deadline = time.monotonic() + 15
                        while not PROCEED.exists():
                            self.assertLess(time.monotonic(), deadline, "first suite was not released")
                            time.sleep(0.02)
        ''' % (str(ready), str(proceed), str(snapshots), PLUGIN)))
        self.commit(self.seed, "suite records exactly what was tested")
        self.git("pull", "-q", "--ff-only", "origin", "main", cwd=self.repo)
        for name in ("first", "second"):
            self.git("checkout", "-q", "-b", "task/" + name, "main", cwd=self.repo)
            self.write(self.repo / (name + ".txt"), name + "\n")
            self.git("add", "-A", cwd=self.repo)
            self.git("commit", "-qm", name + " change", cwd=self.repo)
            self.git("checkout", "-q", "main", cwd=self.repo)
        sources = {name: self.git("rev-parse", "task/" + name, cwd=self.repo) for name in ("first", "second")}

        def wait_for(predicate):
            deadline = time.monotonic() + 10
            while not predicate():
                self.assertLess(time.monotonic(), deadline, "release did not reach synchronization point")
                time.sleep(0.02)

        procs = []
        outputs = [self.home / (name + ".out") for name in ("first", "second")]
        with outputs[0].open("w") as first_out, outputs[1].open("w") as second_out:
            try:
                procs.append(subprocess.Popen(self.cmd("first", "--from-branch", "task/first"), env=self.env,
                                              stdout=first_out, stderr=subprocess.STDOUT))
                wait_for(ready.exists)
                procs.append(subprocess.Popen(self.cmd("second", "--from-branch", "task/second"), env=self.env,
                                              stdout=second_out, stderr=subprocess.STDOUT))
                wait_for(lambda: "waiting for the release lock" in outputs[1].read_text())
                self.assertRegex(outputs[1].read_text(),
                                 r"held by pid %d since \d{2}:\d{2}:\d{2}: first" % procs[0].pid)
                self.assertIsNone(procs[1].poll())
                self.assertEqual(self.version(self.origin)["version"], "0.1.0")
                self.assertFalse((snapshots / "0.1.2.jsonl").exists())
                proceed.touch()
                for p in procs:
                    p.wait(timeout=20)
                self.assertEqual([p.returncode for p in procs], [0, 0], [p.read_text() for p in outputs])
            finally:
                for p in procs:
                    if p.poll() is None:
                        p.kill()
                    p.wait(timeout=5)

        for version, message in (("0.1.1", "first"), ("0.1.2", "second")):
            commit = self.git("log", "--format=%H", "--fixed-strings", "--grep=" + version + ": " + message,
                              "main", cwd=self.origin)
            self.assertTrue(commit)
            paths = self.git("ls-tree", "-r", "--name-only", commit, cwd=self.origin).splitlines()
            pushed = {p: subprocess.check_output(["git", "show", commit + ":" + p], cwd=self.origin,
                                                 env=self.env).hex() for p in paths}
            tested = [json.loads(line) for line in (snapshots / (version + ".jsonl")).read_text().splitlines()]
            self.assertEqual(tested, [pushed])  # once, on exactly the tracked contents that landed
        for name, source in sources.items():
            self.assertEqual(self.git("rev-parse", "task/" + name, cwd=self.repo), source)
            self.assertEqual(self.git("show", "main:" + name + ".txt", cwd=self.origin), name)
        for output in outputs:
            self.assertEqual(output.read_text().count("running the full suite"), 1)
        self.assertEqual(self.version(self.origin)["version"], "0.1.2")
        self.assertEqual(self.market_versions()["iorlas-task-loop"], "0.1.2")
        self.assertEqual(self.git("status", "--porcelain", cwd=self.repo), "")

    def test_minor_bumps_the_minor_and_resets_the_patch(self):
        r = self.release("new feature", "--minor")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.version(self.origin)["version"], "0.2.0")

    def test_a_push_race_rebases_reruns_the_suite_and_takes_the_next_version(self):
        self.git("config", "rebase.updateRefs", "true", cwd=self.repo)
        self.git("checkout", "-q", "-b", "task/race", cwd=self.repo)
        self.write(self.repo / "feature.txt", "survives the push race\n")
        self.git("add", "-A", cwd=self.repo)
        self.git("commit", "-qm", "branch change", cwd=self.repo)
        source = self.git("rev-parse", "HEAD", cwd=self.repo)
        self.git("checkout", "-q", "main", cwd=self.repo)
        # another release lands between our fetch and our push: simulated by a pre-push hook that pushes once
        hook = self.repo / ".git" / "hooks" / "pre-push"
        hook.write_text("#!/bin/sh\nunset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE\n[ -f '%s' ] && exit 0\ntouch '%s'\ncd '%s' && sed -i.bak 's/0.1.0/0.1.1/' %s "
                        "&& rm %s.bak && git commit -qam '0.1.1: racer' && git push -q origin HEAD:main\n"
                        % (self.home / "raced", self.home / "raced", self.seed, PLUGIN, PLUGIN))
        hook.chmod(0o755)
        r = self.release("mine", "--from-branch", "task/race")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("push race", r.stdout)
        self.assertRegex(r.stdout, r"origin/main [0-9a-f]{40} is not the base [0-9a-f]{40}")
        self.assertEqual(self.git("log", "--format=%s", "-3", "main", cwd=self.origin).splitlines(),
                         ["0.1.2: mine", "branch change", "0.1.1: racer"])
        self.assertEqual(self.git("rev-parse", "task/race", cwd=self.repo), source)
        self.assertEqual(self.git("show", "main:feature.txt", cwd=self.origin), "survives the push race")
        self.assertEqual(self.market_versions()["iorlas-task-loop"], "0.1.2")

    def test_a_branch_release_with_nothing_landed_meanwhile_is_no_push_race(self):
        # tl-bxk.12.8: the check compared origin/main with HEAD~1, which is the branch tip once a --from-branch fast-forwarded
        self.git("checkout", "-q", "-b", "task/y", cwd=self.repo)
        self.write(self.repo / "a.txt", "a")
        self.git("add", "-A", cwd=self.repo)
        self.git("commit", "-qm", "a branch commit", cwd=self.repo)
        self.git("checkout", "-q", "main", cwd=self.repo)
        r = self.release("fix", "--from-branch", "task/y")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("push race", r.stdout)
        self.assertEqual(self.git("log", "--format=%s", "-2", "main", cwd=self.origin).splitlines(),
                         ["0.1.1: fix", "a branch commit"])

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
