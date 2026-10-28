"""The real-process race (tl-bxk.11.1, tl-vgo): two `tl loop`s, a hand `run-task --slot s1`, a hand `run-task --slot any --wait`,
a `tl slot hold s2` and two `dev/release.py` at once, all real processes, on a fake repo (bare origin, fake bd, fake
delegate, fake marketplace). About 40 s per seed, more under load; NOT in the default gate (python3 dev/suite.py).

    python3 dev/race.py                  seeds 1..5, one after another
    python3 dev/race.py --seeds 3        one seed (or 1,4,7 or 2-6)
    TASK_LOOP_RACE=1 python3 -m unittest dev.race     the same, one seed (RACE_SEED, default 1)

Exit 0 when every seed passed, 1 when one failed. A failed seed prints `RACE_SEED=n FAILED` and then the checks that broke,
the stderr of every process that exited non-zero, and the tail of every process log; rerun that seed alone to reproduce
(the jitter is seeded, the machine's load is not).

The invariants it checks are each proven deterministically, at the lock and lease level and in the gate, by
tests/test_race_invariants.py; this run is the end-to-end check that the pieces still fit together under real processes.
Nothing may be shared that is not taken through a lock or lease: no bead claimed or run twice, no slot used by two at
once (a hold included), no two beads of one area at once (tl-bxk.11.4), slots served in ticket order (tl-bxk.11.5), no
checkout in a worktree under another process's live engine lock, every land rebased onto the base and pushed once,
every release a distinct version, and nothing left held after all exit.

RACE_SEED sets the jitter (default 1); every process gets one Claude session id, as when one coordinator starts them.
"""

import json
import os
import random
import shutil
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import tl  # noqa: E402
import vendored  # noqa: E402,F401
from process_lock import LockHeldError, ProcessLock  # noqa: E402

PY = sys.executable
BEADS = ["w-%d" % i for i in range(1, 7)]
AREA = {"w-1": "a", "w-2": "a", "w-3": "a", "w-4": "b", "w-5": "b"}  # a by label (lane:a), b by epic (ep-b); w-6: none
SLOTS = ["s1", "s2", "s3"]
DEADLINE = 600  # hang guard, seconds for every process to end (18-49 s seen unloaded; area a runs its 3 beads one after another)
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
@unittest.skipUnless(__name__ == "__main__" or os.environ.get("TASK_LOOP_RACE"), "a real-process race: python3 dev/race.py, or TASK_LOOP_RACE=1")
class Race(unittest.TestCase):
    def setUp(self):
        self.seed = os.environ.get("RACE_SEED", "1")
        self.rnd = random.Random(self.seed)
        self.tmp = tempfile.TemporaryDirectory(prefix="tl-race-")
        h = self.h = Path(os.path.realpath(self.tmp.name))
        for d in ("bin", "home", "cfg", "bd", "hooks"):
            (h / d).mkdir()
        shim(h / "bin" / "bd", FIX / "fake_bd.py")
        (h / "delegate").mkdir()  # the engine reads contract.json beside the route.py it is told to use
        shutil.copy(str(ROOT / "tests" / "fixtures" / "delegate3" / "skills" / "delegate" / "contract.json"), str(h / "delegate" / "contract.json"))
        shutil.copy(str(FIX / "fake_route.py"), str(h / "delegate" / "route.py"))
        # a real `plugin update` leaves the new version in the cache and release.py checks for it (tl-7y6.5.10); the two
        # racing releases publish 0.1.1 and 0.1.2 in either order, so the fake installs both
        cache = h / "home" / ".claude" / "plugins" / "cache" / "iorlas-marketplace" / "iorlas-task-loop"
        (h / "bin" / "claude").write_text('#!/bin/sh\necho "$@" >> "%s"\nfor v in 0.1.1 0.1.2; do mkdir -p "%s/$v/.claude-plugin"; echo "{}" > "%s/$v/.claude-plugin/plugin.json"; done\n'
                                          % (h / "claude.log", cache, cache))
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
                                                       "engine": {"delegate": str(h / "delegate" / "route.py"),
                                                                  "area_label_prefix": "lane:",
                                                                  "areas": {"b": ["ep-b"]}}}, indent=1))
        (r / ".claude-plugin").mkdir()
        (r / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "iorlas-task-loop", "version": "0.1.0"},
                                                                     indent=2) + "\n")
        (r / ".gitignore").write_text("__pycache__/\n")  # the real repo ignores it; the inner suite writes it when bytecode is on
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
        for b, area in AREA.items():
            if area == "a":
                beads[b]["labels"] = ["lane:a"]
            else:
                beads[b]["parent"] = "ep-b"
        beads["ep-b"] = {"id": "ep-b", "title": "epic b", "status": "open", "priority": 2, "issue_type": "epic",
                         "labels": []}
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
        log, err = open(self.h / (name + ".log"), "ab"), open(self.h / (name + ".err"), "ab")
        env = dict(self.env, RACE_ACTOR=name.split("-")[0])  # fake bd notes whose tree claimed
        p = subprocess.Popen(cmd, cwd=str(self.repo), env=env, stdin=subprocess.DEVNULL, stdout=log,
                             stderr=err, start_new_session=True)
        log.close()
        err.close()
        self.procs.append((name, p))
        return p

    def tl(self, name, *args):
        p = self.spawn(name, [PY, str(TL)] + list(args))
        return p.wait(), (self.h / (name + ".log")).read_text(errors="replace") + (self.h / (name + ".err")).read_text(errors="replace")

    def store(self):
        return json.loads((self.h / "bd" / "store.json").read_text())["beads"]

    def hand_run(self, name, bead, delay, *args, fast=False):
        """A person's `tl run-task BEAD ARGS`: the bead is in the loops' queue too. Taken while its slot or area is busy:
        try again; taken because a loop holds the bead: rightly refused, done. fast: through loop_fast (short waits
        in the slot line)."""
        time.sleep(delay)
        out = self.h / (name + ".outcome.json")
        for n in range(400):
            cmd = ["run-task", bead] + list(args) + ["--outcome-file", str(out)]
            if fast:
                p = self.spawn("%s-%d" % (name, n), [PY, str(FIX / "loop_fast.py"), self.seed] + cmd)
                rc = p.wait()
            else:
                rc, _ = self.tl("%s-%d" % (name, n), *cmd)
            r = json.loads(out.read_text()) if out.exists() else {"outcome": "none", "rc": rc}
            self.notes.setdefault(name, []).append(r.get("outcome"))
            b = self.store()[bead]
            if r.get("outcome") != "taken" or b["status"] != "open" or b.get("assignee"):
                return
            time.sleep(0.2)
        self.errors.append("the hand run %s never got in" % name)

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
        parts = ["RACE_SEED=%s" % self.seed]
        for name, p in self.procs:  # the stderr of a process that failed, whole
            err = (self.h / (name + ".err"))
            if p.returncode and err.exists() and err.read_text(errors="replace").strip():
                parts.append("== %s exit %s, stderr\n%s" % (name, p.returncode, err.read_text(errors="replace")))
        for f in sorted(self.h.glob("*.log")):
            parts.append("== %s\n%s" % (f.name, "\n".join(f.read_text(errors="replace").splitlines()[-25:])))
        for f in sorted((self.h / "cfg" / "task-loop" / "loop").glob("*.jsonl")):
            parts.append("== %s\n%s" % (f.name, f.read_text(errors="replace")[-3000:]))
        return "\n".join(parts)

    # -- the test ---------------------------------------------------------------------------------------------------

    def test_two_loops_a_hand_run_a_hold_and_releases_at_once_share_nothing(self):
        t0 = time.time()
        threads = [threading.Thread(target=self.hold, args=(0,)),
                   threading.Thread(target=self.hand_run, args=("hand", "w-1", self.rnd.uniform(0.1, 0.4), "--slot",
                                                                "s1", "--exclusive-area")),
                   threading.Thread(target=self.hand_run, args=("waiter", "w-6", self.rnd.uniform(0.1, 0.6), "--slot",
                                                                "any", "--wait"), kwargs={"fast": True})]
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
        # areas: no two beads of one area held at once, from each won claim to the release that follows it
        held = {}
        for c in claims:
            if c["op"] == "claim":
                held.setdefault(c["bead"], []).append([c["t"], None])
            elif c["op"].startswith("release:") and held.get(c["bead"]) and held[c["bead"]][-1][1] is None:
                held[c["bead"]][-1][1] = c["t"]
        spans_area = sorted((t0, t1 or 1e18, b) for b, ts in held.items() for t0, t1 in ts if AREA.get(b))
        for i, (a0, a1, a) in enumerate(spans_area):
            for b0, b1, b in spans_area[i + 1:]:
                if b0 < a1 and AREA[a] == AREA[b]:
                    self.fail("%s and %s of area %s held at once%s" % (a, b, AREA[a], msg))

        # the slot line: takes by waiters in ticket order; no ticket left
        events = jsonl(self.h / "cfg" / "task-loop" / "events.jsonl")
        tickets = [e["ticket"] for e in events if e["kind"] == "slot-take" and "ticket" in e]
        self.assertGreaterEqual(len(tickets), 2, msg)
        self.assertEqual(tickets, sorted(set(tickets)), "slots not served in ticket order" + msg)
        self.assertEqual(list((self.h / "cfg" / "task-loop" / "slots").glob("*/*.json")), [], msg)

        # the race happened: two slots were in use at once (from the slot takes and releases tl.py records)
        inuse, busy = {}, 0
        for e in events:
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
            try:
                ProcessLock.acquire(lock).release()  # LockHeldError while a process still holds it
            except LockHeldError as e:
                self.fail("lock left held: %s" % e)
        self.assertEqual(sorted(p.name for p in (cfg / "loop").glob("*") if p.suffix in (".json", ".stop")), [])
        print("race duration (metric only): %.1f s" % secs)


def seeds_of(text):
    """'1,4' -> [1, 4]; '2-6' -> [2..6]; '3' -> [3]."""
    out = []
    for part in text.split(","):
        lo, _, hi = part.partition("-")
        out += list(range(int(lo), int(hi or lo) + 1))
    return out


def main(argv=None):
    import argparse
    import io
    ap = argparse.ArgumentParser(prog="race.py", description="The real-process race, one run per seed (see the file docstring).")
    ap.add_argument("--seeds", default="1-5", help="seeds to run: 1-5 (default), 3, or 1,4,7")
    args = ap.parse_args(argv)
    failed = []
    for seed in seeds_of(args.seeds):
        os.environ["RACE_SEED"] = str(seed)
        out = io.StringIO()
        t = time.time()
        res = unittest.TextTestRunner(stream=out, verbosity=0).run(unittest.defaultTestLoader.loadTestsFromTestCase(Race))
        ok = res.wasSuccessful() and not res.skipped
        print("RACE_SEED=%d %s in %.0f s" % (seed, "ok" if ok else "FAILED", time.time() - t), flush=True)
        if not ok:
            failed.append(seed)
            print(out.getvalue(), file=sys.stderr, flush=True)
    print("failed seeds: %s" % (failed or "none"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
