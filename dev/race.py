#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["msgspec==0.22.0"]
# ///
"""The real-process race (tl-bxk.11.1, tl-vgo): two `tl loop`s, a hand `run-task --slot s1`, a hand `run-task --slot any --wait`,
a `tl slot hold s2` and two `dev/release.py` at once, all real processes, on a fake repo (bare origin, fake bd, fake
delegate, fake marketplace). About 40 s per seed, more under load; NOT in the default gate (uv run --script dev/suite.py).

    uv run --script dev/race.py                  seeds 1..5, one after another
    uv run --script dev/race.py --seeds 3        one seed (or 1,4,7 or 2-6)
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

import argparse
import io
import json
import os
import random
import shutil
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
sys.path.insert(0, str(ROOT / "tests"))
sys.path.append(str(ROOT / "skills" / "task-loop" / "_vendor"))  # before the shelf imports below, as tests/support/paths.py does
sys.path.append(str(ROOT / "src"))
import stream_proc  # noqa: E402
import support.paths  # noqa: E402, F401
from process_lock import LockHeldError, ProcessLock  # noqa: E402

from taskloop.adapters import ident  # noqa: E402
from taskloop.app.slots import (  # noqa: E402
    engine_lock,
    marks,
)
from taskloop.app.wire import slots as wslots  # noqa: E402

PY = sys.executable
BEADS = [f"w-{i}" for i in range(1, 7)]
AREA = {"w-1": "a", "w-2": "a", "w-3": "a", "w-4": "b", "w-5": "b"}  # a by label (lane:a), b by epic (ep-b); w-6: none
SLOTS = ["s1", "s2", "s3"]
DEADLINE = 600  # hang guard, seconds for every process to end (18-49 s seen unloaded; area a runs its 3 beads one after another)
DROP = ("CLAUDE", "ANTHROPIC_", "TASK_LOOP_", "DELEGATE_", "CODEX", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
        "XDG_", "APPDATA", "BD_", "BEADS_")


def sh(*a, cwd, env):
    r = subprocess.run(list(a), cwd=str(cwd), env=env, capture_output=True, text=True, check=False)
    if r.returncode:
        raise AssertionError("{} failed: {}".format(" ".join(a), r.stdout + r.stderr))
    return r.stdout.strip()


def jsonl(path):
    try:
        return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        return []


def shim(path, script):
    path.write_text(f"#!{PY}\nimport runpy, sys\nsys.argv[0] = {str(script)!r}\nrunpy.run_path({str(script)!r}, run_name='__main__')\n")
    path.chmod(0o755)


@unittest.skipIf(os.name == "nt", "fcntl locks and POSIX process groups")
@unittest.skipUnless(
    __name__ == "__main__" or os.environ.get("TASK_LOOP_RACE"), "a real-process race: uv run --script dev/race.py, or TASK_LOOP_RACE=1"
)
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
        shutil.copy(
            str(ROOT / "tests" / "fixtures" / "delegate3" / "skills" / "delegate" / "contract.json"), str(h / "delegate" / "contract.json")
        )
        shutil.copy(str(FIX / "fake_route.py"), str(h / "delegate" / "route.py"))
        # a real `plugin update` leaves the new version in the cache and release.py checks for it (tl-7y6.5.10); the two
        # racing releases publish 0.1.1 and 0.1.2 in either order, so the fake installs both
        cache = h / "home" / ".claude" / "plugins" / "cache" / "iorlas-marketplace" / "iorlas-task-loop"
        (h / "bin" / "claude").write_text(
            ('#!/bin/sh\necho "$@" >> "{}"\nfor v in 0.1.1 0.1.2; do mkdir -p "{}/$v/.claude-plugin"; echo "{{}}" > '
             '"{}/$v/.claude-plugin/plugin.json"; done\n').format(
                h / "claude.log", cache, cache
            )
        )
        (h / "bin" / "claude").chmod(0o755)
        shim(h / "hooks" / "post-checkout", FIX / "post_checkout.py")
        env = {k: v for k, v in os.environ.items() if not k.startswith(DROP)}
        env.update(HOME=str(h / "home"), XDG_CONFIG_HOME=str(h / "cfg"), APPDATA=str(h / "cfg"),
                   PATH="{}{}{}".format(h / "bin", os.pathsep, os.environ["PATH"]), FAKE_BD_DIR=str(h / "bd"),
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
                                                                  "areas": {"b": ["ep-b"]}},
                                                       "loop": {"poll": 0.2, "pause_retry": 2, "area_poll": 0.3}}, indent=1))
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
        wslots.exclude_local(str(r), ".slots/", ".task/")
        for s in SLOTS:
            sh("git", "worktree", "add", "-q", "--detach", str(r / ".slots" / s), "origin/main", cwd=r, env=env)
        beads = {b: {"id": b, "title": "bead " + b, "status": "open", "priority": 2, "issue_type": "task",
                     "acceptance_criteria": f"f-{b}.txt exists", "labels": []} for b in BEADS}
        for b, area in AREA.items():
            if area == "a":
                beads[b]["labels"] = ["lane:a"]
            else:
                beads[b]["parent"] = "ep-b"
        beads["ep-b"] = {"id": "ep-b", "title": "epic b", "status": "open", "priority": 2, "issue_type": "epic",
                         "labels": []}
        for i, s in enumerate(SLOTS, 1):
            beads[f"sl-{i}"] = {"id": f"sl-{i}", "title": f"slot {ident.hostname()} {s}", "status": "open",
                                  "priority": 4, "issue_type": "chore", "labels": ["slot"], "assignee": ""}
        (h / "bd" / "store.json").write_text(json.dumps({"beads": beads}))
        self.seed_market()
        self.procs, self.errors, self.notes = [], [], {}

    def seed_market(self):
        h, env = self.h, self.env
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

    def tearDown(self):
        self.kill_all()
        self.tmp.cleanup()

    # -- the actors -------------------------------------------------------------------------------------------------

    def spawn(self, name, cmd):
        env = dict(self.env, RACE_ACTOR=name.split("-")[0])  # fake bd notes whose tree claimed
        with open(self.h / (name + ".log"), "ab") as log, open(self.h / (name + ".err"), "ab") as err:
            p = subprocess.Popen(cmd, cwd=str(self.repo), env=env, stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=err, start_new_session=True)
        self.procs.append((name, p))
        return p

    def tl(self, name, *args):
        p = self.spawn(name, [PY, str(TL), *args])
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
            cmd = ["run-task", bead, *args, "--outcome-file", str(out)]
            if fast:
                p = self.spawn(f"{name}-{n}", [PY, str(FIX / "loop_fast.py"), self.seed, *cmd])
                rc = p.wait()
            else:
                rc, _ = self.tl(f"{name}-{n}", *cmd)
            r = json.loads(out.read_text()) if out.exists() else {"outcome": "none", "rc": rc}
            self.notes.setdefault(name, []).append(r.get("outcome"))
            b = self.store()[bead]
            if r.get("outcome") != "taken" or b["status"] != "open" or b.get("assignee"):
                return
            time.sleep(0.2)
        self.errors.append(f"the hand run {name} never got in")

    def hold(self, delay):
        """A person holds s2 (screenshots), works in it for 3 s (the hold must still be on its bead), then releases it."""
        time.sleep(delay)
        for n in range(200):
            rc, _ = self.tl(f"hold-{n}", "slot", "hold", "s2", "--why", "race test", "--for", "0.5")
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
        if float((sb.get("metadata") or {}).get("hold_until") or 0) <= time.time() or sb.get("status") != "in_progress":
            self.errors.append(f"the hold on s2 was lost while it was used: {sb}")
        rc, out = self.tl("hold-release", "slot", "release", "s2")
        if rc:
            self.errors.append(f"tl slot release s2: {out}")
        self.notes["hold"] = (held, released)

    def kill_all(self):
        for _, p in self.procs:  # each child leads a session of its own: stream-proc ends its whole tree (setsid'd run-tasks included)
            if p.poll() is None:
                stream_proc.stop_tree(p, grace=1.0)

    def dump(self):
        parts = [f"RACE_SEED={self.seed}"]
        for name, p in self.procs:  # the stderr of a process that failed, whole
            err = (self.h / (name + ".err"))
            if p.returncode and err.exists() and err.read_text(errors="replace").strip():
                parts.append("== {} exit {}, stderr\n{}".format(name, p.returncode, err.read_text(errors="replace")))
        for f in sorted(self.h.glob("*.log")):
            parts.append("== {}\n{}".format(f.name, "\n".join(f.read_text(errors="replace").splitlines()[-25:])))
        for f in sorted(
            (self.h / "cfg" / "task-loop" / "engine").glob("*.jsonl")
        ):  # a run that did not land: why, from its own log (tl-bjd)
            lines = f.read_text(errors="replace").splitlines()
            if lines and "landed" not in lines[-1]:
                parts.append("== engine log {} (did not land), last records\n{}".format(f.name, "\n".join(ln[:600] for ln in lines[-8:])))
        for f in sorted((self.h / "cfg" / "task-loop" / "loop").glob("*.jsonl")):
            parts.append("== {}\n{}".format(f.name, f.read_text(errors="replace")[-3000:]))
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
            self.spawn(f"loop{i}", [PY, str(FIX / "loop_fast.py"), f"{self.seed}-{i}", "loop", "--repo",
                                      str(self.repo)])
        time.sleep(self.rnd.uniform(1.0, 3.0))
        for i in (1, 2):
            self.spawn(f"release{i}", [PY, str(RELEASE), f"race release {i}", "--repo", str(self.repo),
                                         "--marketplace", str(self.market)])
        for t in threads:
            t.join(max(1, DEADLINE - (time.time() - t0)))
        for name, p in list(self.procs):
            try:
                p.wait(max(1, DEADLINE - (time.time() - t0)))
            except subprocess.TimeoutExpired:
                self.kill_all()
                self.fail(f"{name} still ran after {int(DEADLINE)} s\n{self.dump()}")
        self.check(time.time() - t0)

    def check(self, secs):
        msg = "\n" + self.dump()
        self.assertEqual(self.errors, [], msg)
        for name, p in self.procs:
            if name.startswith(("loop", "release", "hold-release")):
                self.assertEqual(p.returncode, 0, f"{name} exit {p.returncode}{msg}")
        beads = self.store()
        claims, runs = self.check_landed_once(beads, msg)
        self.check_slot_and_area_exclusion(claims, runs, msg)
        self.check_the_slot_line(msg)
        self.check_origin(msg)
        self.check_nothing_held(beads)
        print(f"race duration (metric only): {secs:.1f} s")

    def check_landed_once(self, beads, msg):
        # every bead landed once, claimed by one actor, its worker run once
        self.assertEqual({b: beads[b]["status"] for b in BEADS}, dict.fromkeys(BEADS, "closed"), msg)
        claims = jsonl(self.h / "bd" / "claims.jsonl")
        for b in BEADS:
            who = {(c["tree"], c["by"]) for c in claims if c["bead"] == b and c["op"] in ("claim", "reclaim")}
            self.assertEqual(len(who), 1, f"{b} claimed by {sorted(who)}{msg}")
        runs = jsonl(self.h / "route.jsonl")
        self.assertEqual(sorted(r["bead"] for r in runs), sorted(BEADS), msg)

        return claims, runs

    def check_slot_and_area_exclusion(self, claims, runs, msg):
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
                    self.assertNotEqual(a[2], b[2], f"{a[3]} and {b[3]} in one slot at once{msg}")
        # areas: no two beads of one area held at once, from each won claim to the release that follows it
        held: dict[str, list[list[float | None]]] = {}
        for c in claims:
            if c["op"] == "claim":
                held.setdefault(c["bead"], []).append([c["t"], None])
            elif c["op"].startswith("release:") and held.get(c["bead"]) and held[c["bead"]][-1][1] is None:
                held[c["bead"]][-1][1] = c["t"]
        spans_area = sorted((t0 or 0.0, t1 or 1e18, b) for b, ts in held.items() for t0, t1 in ts if AREA.get(b))
        for i, (_a0, a1, a) in enumerate(spans_area):
            for b0, _b1, b in spans_area[i + 1:]:
                if b0 < a1 and AREA[a] == AREA[b]:
                    self.fail(f"{a} and {b} of area {AREA[a]} held at once{msg}")

    def check_the_slot_line(self, msg):
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

    def check_origin(self, msg):
        # origin: linear, one commit per bead, one per release, distinct versions
        log = sh("git", "--git-dir", str(self.origin), "log", "--format=%P|%s", "main", cwd=self.h, env=self.env)
        lines = [ln.split("|", 1) for ln in log.splitlines()]
        self.assertFalse([s for p, s in lines if len(p.split()) > 1], "a merge on main" + msg)
        subjects = [s for _, s in lines]
        for b in BEADS:
            self.assertEqual(sum(s.endswith(f"({b})") for s in subjects), 1, f"{b} on main{msg}")
        versions = [s.split(":")[0] for s in subjects if "race release" in s]
        self.assertEqual(len(versions), 2, msg)
        self.assertEqual(sorted(versions), ["0.1.1", "0.1.2"], msg)
        self.assertEqual(len(subjects), 1 + len(BEADS) + 2, subjects)
        market = sh("git", "--git-dir", str(self.h / "m.git"), "show", "main:.claude-plugin/marketplace.json",
                    cwd=self.h, env=self.env)
        self.assertEqual(json.loads(market)["plugins"][0]["version"], "0.1.2")

    def check_nothing_held(self, beads):
        # nothing left held
        for i, s in enumerate(SLOTS, 1):
            sb = beads[f"sl-{i}"]
            self.assertEqual((sb["status"], sb.get("assignee") or ""), ("open", ""), sb)
            self.assertFalse(set(sb.get("metadata") or {}) & set(marks.HELD_KEYS), sb)
            self.assertFalse(engine_lock.engine_lock_path(str(self.repo / ".slots" / s)).exists(), s)
        cfg = self.h / "cfg" / "task-loop"
        for lock in (cfg / "locks").glob("*.lock"):
            try:
                ProcessLock.acquire(lock).release()  # LockHeldError while a process still holds it
            except LockHeldError as e:
                self.fail(f"lock left held: {e}")
        self.assertEqual(sorted(p.name for p in (cfg / "loop").glob("*") if p.suffix == ".json"), [])


def seeds_of(text):
    """'1,4' -> [1, 4]; '2-6' -> [2..6]; '3' -> [3]."""
    out = []
    for part in text.split(","):
        lo, _, hi = part.partition("-")
        out += list(range(int(lo), int(hi or lo) + 1))
    return out


def main(argv=None):
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
        print("RACE_SEED={:d} {} in {:.0f} s".format(int(seed), "ok" if ok else "FAILED", time.time() - t), flush=True)
        if not ok:
            failed.append(seed)
            print(out.getvalue(), file=sys.stderr, flush=True)
    print("failed seeds: {}".format(failed or "none"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
