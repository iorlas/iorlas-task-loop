"""Safe by construction (tl-bxk.11.1): two `tl loop`s, a hand `run-task --slot s1`, a `tl slot hold s2` and two
`dev/release.py` at once, all real processes, on a fake repo (bare origin, fake bd, fake delegate, fake marketplace).

Nothing may be shared that is not taken through a lock or lease: no bead claimed or run twice, no slot used by two at
once (a hold included), no checkout in a worktree under another process's live engine lock, every land rebased onto
the base and pushed once, every release a distinct version, and nothing left held after all exit.

RACE_SEED sets the jitter (default 1); every process gets one Claude session id, as when one coordinator starts them.
"""

import fcntl
import json
import os
import random
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "race"
TL = ROOT / "skills" / "task-loop" / "tl.py"
RELEASE = ROOT / "dev" / "release.py"
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import tl  # noqa: E402

PY = sys.executable
BEADS = ["w-%d" % i for i in range(1, 7)]
SLOTS = ["s1", "s2", "s3"]
DEADLINE = 100  # seconds for every process to end; the whole test stays under 2 minutes
DROP = ("CLAUDE", "ANTHROPIC_", "TASK_LOOP_", "DELEGATE_", "CODEX", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
        "XDG_", "APPDATA", "BD_", "BEADS_")


def sh(*a, cwd, env):
    r = subprocess.run(list(a), cwd=str(cwd), env=env, capture_output=True, text=True)
    if r.returncode:
        raise AssertionError("%s failed: %s" % (" ".join(a), r.stdout + r.stderr))
    return r.stdout.strip()


def jsonl(path):
    try:
        return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        return []


def shim(path, script):
    path.write_text("#!%s\nimport runpy, sys\nsys.argv[0] = %r\nrunpy.run_path(%r, run_name='__main__')\n"
                    % (PY, str(script), str(script)))
    path.chmod(0o755)


@unittest.skipIf(os.name == "nt", "fcntl locks and POSIX process groups")
class Race(unittest.TestCase):
    def setUp(self):
        self.seed = os.environ.get("RACE_SEED", "1")
        self.rnd = random.Random(self.seed)
        self.tmp = tempfile.TemporaryDirectory(prefix="tl-race-")
        h = self.h = Path(os.path.realpath(self.tmp.name))
        for d in ("bin", "home", "cfg", "bd", "hooks"):
            (h / d).mkdir()
        shim(h / "bin" / "bd", FIX / "fake_bd.py")
        (h / "bin" / "claude").write_text('#!/bin/sh\necho "$@" >> "%s"\n' % (h / "claude.log"))
        (h / "bin" / "claude").chmod(0o755)
        shim(h / "hooks" / "post-checkout", FIX / "post_checkout.py")
        env = {k: v for k, v in os.environ.items() if not k.startswith(DROP)}
        env.update(HOME=str(h / "home"), XDG_CONFIG_HOME=str(h / "cfg"), APPDATA=str(h / "cfg"),
                   PATH="%s%s%s" % (h / "bin", os.pathsep, os.environ["PATH"]), FAKE_BD_DIR=str(h / "bd"),
                   FAKE_ROUTE_LOG=str(h / "route.jsonl"), FAKE_CHECKOUT_LOG=str(h / "checkout.jsonl"),
                   RACE_SEED=self.seed, CLAUDE_CODE_SESSION_ID="race0000-coordinator", GIT_AUTHOR_NAME="t",
                   GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                   GIT_CONFIG_NOSYSTEM="1", TASK_LOOP_DASH_PORT="1")
        self.env = env
        self.origin, self.repo = h / "o.git", h / "repo"
        sh("git", "init", "-q", "--bare", "-b", "main", str(self.origin), cwd=h, env=env)
        sh("git", "clone", "-q", str(self.origin), str(self.repo), cwd=h, env=env)
        r = self.repo
        sh("git", "checkout", "-q", "-B", "main", cwd=r, env=env)
        (r / ".task-loop.json").write_text(json.dumps({"slots": {"count": len(SLOTS)},
                                                       "engine": {"delegate": str(FIX / "fake_route.py")}}, indent=1))
        (r / ".claude-plugin").mkdir()
        (r / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "iorlas-task-loop", "version": "0.1.0"},
                                                                     indent=2) + "\n")
        (r / "tests").mkdir()
        (r / "tests" / "test_ok.py").write_text("import time\nimport unittest\n\n\nclass T(unittest.TestCase):\n"
                                                "    def test_ok(self):\n        time.sleep(0.5)\n")
        sh("git", "add", "-A", cwd=r, env=env)
        sh("git", "commit", "-qm", "seed", cwd=r, env=env)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=r, env=env)
        sh("git", "branch", "-q", "--set-upstream-to", "origin/main", cwd=r, env=env)
        sh("git", "config", "core.hooksPath", str(h / "hooks"), cwd=r, env=env)
        tl.exclude_local(str(r), ".slots/", ".task/")
        for s in SLOTS:
            sh("git", "worktree", "add", "-q", "--detach", str(r / ".slots" / s), "origin/main", cwd=r, env=env)
        beads = {b: {"id": b, "title": "bead " + b, "status": "open", "priority": 2, "issue_type": "task",
                     "acceptance_criteria": "f-%s.txt exists" % b, "labels": []} for b in BEADS}
        for i, s in enumerate(SLOTS, 1):
            beads["sl-%d" % i] = {"id": "sl-%d" % i, "title": "slot %s %s" % (tl.HOST, s), "status": "open",
                                  "priority": 4, "issue_type": "chore", "labels": ["slot"], "assignee": ""}
        (h / "bd" / "store.json").write_text(json.dumps({"beads": beads}))
        mo, self.market = h / "m.git", h / "market"
        sh("git", "init", "-q", "--bare", "-b", "main", str(mo), cwd=h, env=env)
        sh("git", "clone", "-q", str(mo), str(self.market), cwd=h, env=env)
        sh("git", "checkout", "-q", "-B", "main", cwd=self.market, env=env)
        (self.market / ".claude-plugin").mkdir()
        (self.market / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
            {"name": "iorlas-marketplace", "plugins": [{"name": "iorlas-task-loop", "source": "x", "version": "0.1.0"}]},
            indent=2) + "\n")
        sh("git", "add", "-A", cwd=self.market, env=env)
        sh("git", "commit", "-qm", "seed", cwd=self.market, env=env)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.market, env=env)
        self.procs, self.errors, self.notes = [], [], {}

    def tearDown(self):
        self.kill_all()
        self.tmp.cleanup()

    # -- the actors -------------------------------------------------------------------------------------------------

    def spawn(self, name, cmd):
        log = open(self.h / (name + ".log"), "ab")
        env = dict(self.env, RACE_ACTOR=name.split("-")[0])  # fake bd notes whose tree claimed
        p = subprocess.Popen(cmd, cwd=str(self.repo), env=env, stdin=subprocess.DEVNULL, stdout=log,
                             stderr=subprocess.STDOUT, start_new_session=True)
        log.close()
        self.procs.append((name, p))
        return p

    def tl(self, name, *args):
        p = self.spawn(name, [PY, str(TL)] + list(args))
        return p.wait(), (self.h / (name + ".log")).read_text(errors="replace")

    def store(self):
        return json.loads((self.h / "bd" / "store.json").read_text())["beads"]

    def hand_run(self, delay):
        """A person's `tl run-task w-1 --slot s1`: w-1 is in the loops' queue too. Taken while s1 is busy: try again;
        taken because a loop holds w-1: rightly refused, done."""
        time.sleep(delay)
        out = self.h / "hand.outcome.json"
        for n in range(200):
            rc, _ = self.tl("hand-%d" % n, "run-task", "w-1", "--slot", "s1", "--outcome-file", str(out))
            r = json.loads(out.read_text()) if out.exists() else {"outcome": "none", "rc": rc}
            self.notes.setdefault("hand", []).append(r.get("outcome"))
            b = self.store()["w-1"]
            if r.get("outcome") != "taken" or b["status"] != "open" or b.get("assignee"):
                return
            time.sleep(0.2)
        self.errors.append("the hand run never got in")

    def hold(self, delay):
        """A person holds s2 (screenshots), works in it for 3 s (the hold must still be on its bead), then releases it."""
        time.sleep(delay)
        for n in range(200):
            rc, _ = self.tl("hold-%d" % n, "slot", "hold", "s2", "--why", "race test", "--for", "0.5")
            if rc == 0:
                break
            time.sleep(0.2)
        else:
            self.errors.append("the hold never got s2")
            return
        held = time.time()
        time.sleep(3)
        released = time.time()
        sb = self.store()["sl-2"]  # still held, by the hold: no release or clean-up wiped it meanwhile
        if not tl.slot_hold(sb) or sb.get("status") != "in_progress":
            self.errors.append("the hold on s2 was lost while it was used: %s" % sb)
        rc, out = self.tl("hold-release", "slot", "release", "s2")
        if rc:
            self.errors.append("tl slot release s2: %s" % out)
        self.notes["hold"] = (held, released)

    def kill_all(self):
        for _, p in self.procs:
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass
        try:  # run-task children run in sessions of their own: found by the temp dir in their command line
            out = subprocess.run(["ps", "-A", "-o", "pid=,args="], capture_output=True, text=True).stdout
        except OSError:
            out = ""
        for ln in out.splitlines():
            pid, _, cmd = ln.strip().partition(" ")
            if str(self.h) in cmd and pid.isdigit() and int(pid) != os.getpid():
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except OSError:
                    pass

    def dump(self):
        parts = []
        for f in sorted(self.h.glob("*.log")):
            parts.append("== %s\n%s" % (f.name, "\n".join(f.read_text(errors="replace").splitlines()[-25:])))
        for f in sorted((self.h / "cfg" / "task-loop" / "loop").glob("*.jsonl")):
            parts.append("== %s\n%s" % (f.name, f.read_text(errors="replace")[-3000:]))
        return "\n".join(parts)

    # -- the test ---------------------------------------------------------------------------------------------------

    def test_two_loops_a_hand_run_a_hold_and_releases_at_once_share_nothing(self):
        t0 = time.time()
        threads = [threading.Thread(target=self.hold, args=(0,)),
                   threading.Thread(target=self.hand_run, args=(self.rnd.uniform(0.1, 0.4),))]
        for t in threads:
            t.start()
        for i in (1, 2):
            time.sleep(self.rnd.uniform(0.1, 0.4))
            self.spawn("loop%d" % i, [PY, str(FIX / "loop_fast.py"), "%s-%d" % (self.seed, i), "loop", "--repo",
                                      str(self.repo)])
        time.sleep(self.rnd.uniform(1.0, 3.0))
        for i in (1, 2):
            self.spawn("release%d" % i, [PY, str(RELEASE), "race release %d" % i, "--repo", str(self.repo),
                                         "--marketplace", str(self.market)])
        for t in threads:
            t.join(max(1, DEADLINE - (time.time() - t0)))
        for name, p in list(self.procs):
            try:
                p.wait(max(1, DEADLINE - (time.time() - t0)))
            except subprocess.TimeoutExpired:
                self.kill_all()
                self.fail("%s still ran after %d s\n%s" % (name, DEADLINE, self.dump()))
        self.check(time.time() - t0)

    def check(self, secs):
        msg = "\n" + self.dump()
        self.assertEqual(self.errors, [], msg)
        for name, p in self.procs:
            if name.startswith(("loop", "release", "hold-release")):
                self.assertEqual(p.returncode, 0, "%s exit %s%s" % (name, p.returncode, msg))
        beads = self.store()

        # every bead landed once, claimed by one actor, its worker run once
        self.assertEqual({b: beads[b]["status"] for b in BEADS}, {b: "closed" for b in BEADS}, msg)
        claims = jsonl(self.h / "bd" / "claims.jsonl")
        for b in BEADS:
            who = {(c["tree"], c["by"]) for c in claims if c["bead"] == b and c["op"] in ("claim", "reclaim")}
            self.assertEqual(len(who), 1, "%s claimed by %s%s" % (b, sorted(who), msg))
        runs = jsonl(self.h / "route.jsonl")
        self.assertEqual(sorted(r["bead"] for r in runs), sorted(BEADS), msg)

        # no worktree changed under a live engine; one user per slot at a time, the hold included
        for r in runs:
            self.assertEqual((r["start"]["branch"], r["end"]["branch"]), ("task/" + r["bead"],) * 2, r)
            self.assertEqual((r["start"]["lock"], r["end"]["lock"]), (r["engine"],) * 2, r)
        checkouts = jsonl(self.h / "checkout.jsonl")
        self.assertEqual([c for c in checkouts if not c["ok"]], [], "checkouts under another's live engine lock" + msg)
        self.assertTrue([c for c in checkouts if c.get("lock")], "the hook saw no checkout under a live lock" + msg)
        spans = sorted((r["start"]["t"], r["end"]["t"], r["cwd"], r["bead"]) for r in runs)
        held, released = self.notes["hold"]
        s2 = os.path.realpath(str(self.repo / ".slots" / "s2"))
        spans_s2 = [s for s in spans if s[2] == s2]
        self.assertFalse([s for s in spans_s2 if s[0] < released and s[1] > held], "ran in s2 during the hold" + msg)
        for i, a in enumerate(spans):
            for b in spans[i + 1:]:
                if b[0] < a[1]:
                    self.assertNotEqual(a[2], b[2], "%s and %s in one slot at once%s" % (a[3], b[3], msg))
        # the race happened: two slots were in use at once (from the slot takes and releases tl.py records)
        inuse, busy = {}, 0
        for e in jsonl(self.h / "cfg" / "task-loop" / "events.jsonl"):
            if e["kind"] == "slot-take":  # a loop's or the hand run's, never the hold
                inuse[e["slot"]] = True
            elif e["kind"] == "slot-release":
                inuse.pop(e["slot"], None)
            busy = max(busy, len(inuse))
        self.assertGreaterEqual(busy, 2, "never two slots in use at once: the race never happened" + msg)

        # origin: linear, one commit per bead, one per release, distinct versions
        log = sh("git", "--git-dir", str(self.origin), "log", "--format=%P|%s", "main", cwd=self.h, env=self.env)
        lines = [ln.split("|", 1) for ln in log.splitlines()]
        self.assertFalse([s for p, s in lines if len(p.split()) > 1], "a merge on main" + msg)
        subjects = [s for _, s in lines]
        for b in BEADS:
            self.assertEqual(sum(s.endswith("(%s)" % b) for s in subjects), 1, "%s on main%s" % (b, msg))
        versions = [s.split(":")[0] for s in subjects if "race release" in s]
        self.assertEqual(len(versions), 2, msg)
        self.assertEqual(sorted(versions), ["0.1.1", "0.1.2"], msg)
        self.assertEqual(len(subjects), 1 + len(BEADS) + 2, subjects)
        market = sh("git", "--git-dir", str(self.h / "m.git"), "show", "main:.claude-plugin/marketplace.json",
                    cwd=self.h, env=self.env)
        self.assertEqual(json.loads(market)["plugins"][0]["version"], "0.1.2")

        # nothing left held
        for i, s in enumerate(SLOTS, 1):
            sb = beads["sl-%d" % i]
            self.assertEqual((sb["status"], sb.get("assignee") or ""), ("open", ""), sb)
            self.assertFalse(set((sb.get("metadata") or {})) & set(tl.HELD_KEYS), sb)
            self.assertFalse(tl.engine_lock_path(str(self.repo / ".slots" / s)).exists(), s)
        cfg = self.h / "cfg" / "task-loop"
        for lock in (cfg / "locks").glob("*.lock"):
            with open(lock, "a+") as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises while a process still holds it
        self.assertEqual(sorted(p.name for p in (cfg / "loop").glob("*") if p.suffix in (".json", ".stop")), [])
        self.assertLess(secs, DEADLINE)


if __name__ == "__main__":
    unittest.main()
