"""The race invariants (tl-vgo), one deterministic test each, in the gate. The real-process race (dev/race.py) checks the same
rules with seven real processes and random jitter; here the real lock, lease and claim code of tl.py, loop.py, engine.py and
dev/release.py runs with threads, events and a fake clock: no child process, no sleep, no wall-clock threshold.

How a race is made certain: thread A is held inside the guarded step (its first bead claim, the engine lock take, the push)
until thread B has reached the same place or the lock in front of it. With the lock, B stops at the lock and A goes on;
without it, B walks in beside A. The wait has a 60 s hang guard, never a measure.

Each test names the one-line sabotage that turns it red ("Red when"); every one was run once against the broken code.

invariant (dev/race.py docstring)                      test
no bead claimed or run twice                           test_no_bead_is_claimed_twice
no slot used by two at once, a hold included           test_no_slot_is_used_by_two_at_once_a_hold_included
no two beads of one area at once                       test_no_two_beads_of_one_area_run_at_once
slots served in ticket order                           test_slots_are_served_in_ticket_order_priority_first
no checkout under another process's live engine lock   test_no_checkout_happens_under_a_live_engine_lock
every land under the land lock, rebased, pushed once   test_every_land_holds_the_land_lock_and_is_rebased_and_pushed_once
every release a distinct version                       test_every_release_takes_a_distinct_version
nothing left held after all exit                       test_nothing_is_left_held_after_everyone_is_done
"""

import contextlib
import io
import json
import os
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -m unittest tests.test_race_invariants, from the repo root
import test_loop  # noqa: E402  (puts skills/task-loop on sys.path)

import clock as clocks  # noqa: E402
import engine  # noqa: E402
from support.builders import cfg_with  # noqa: E402
import loop  # noqa: E402
import tl  # noqa: E402
from support import tlbd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev"))
import release  # noqa: E402

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

GUARD = 60  # hang guard only, seconds: no assertion reads a duration
OTHER_ENGINE = 4242  # a pid the fake process table says is alive, and not ours
Args = engine.Args


class SafeBd(test_loop.FakeBd):
    """bd as one tracker for many threads: every call under one lock, bd 1.3's claim (the bead's own assignee claims it again,
    which is why one session's two hand runs are told apart by the slot lock and not by bd), `before` called first and outside the lock."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.mu = threading.RLock()
        self.won = []  # (bead, actor) of every claim that took a bead that was not held
        self.before = lambda a: None

    def __call__(self, *a, cwd=None, check=False):
        self.before(a)
        with self.mu:
            b = (self.beads.get(a[1]) or self.slots.get(a[1])) if len(a) > 1 else None
            was = (b or {}).get("status")
            if a[0] == "update" and "--claim" in a and b and was == "in_progress" and b.get("assignee") == tl.actor():
                return mock.Mock(returncode=0, stdout="", stderr="")
            r = super().__call__(*a, cwd=cwd, check=check)
            if b and was != "in_progress" and b.get("status") == "in_progress":
                self.won.append((a[1], tl.actor()))
            return r


def claims(a):
    return a[:1] == ("update",) and "--claim" in a


@unittest.skipIf(os.name == "nt", "fcntl locks (tl has none on Windows: documented no-op)")
class Invariants(test_loop.Base):
    def setUp(self):
        super().setUp()
        self.clock = clocks.FakeClock(1_800_000_000.0)
        self.live = {os.getpid()}  # the fake process table: a pid in it is alive
        self.actors = {}  # thread name -> actor name (default: the thread's name)
        self.out = io.StringIO()
        for p in (mock.patch.object(tl, "now", side_effect=self.clock.now),
                  mock.patch.object(tl, "actor", side_effect=lambda: self.actors.get(threading.current_thread().name,
                                                                                    threading.current_thread().name)),
                  mock.patch.object(tl, "proc_alive", side_effect=lambda pid, start="": int(pid) in self.live),
                  mock.patch.object(tl, "proc_start", side_effect=lambda pid: "T%s" % pid),
                  mock.patch.object(tl, "git", return_value=""),  # no git, no child process
                  mock.patch.object(sys, "stdout", self.out)):
            p.start()
            self.addCleanup(p.stop)
        self.repo_s = str(self.repo)
        self.lock_calls = []  # (thread name) of every tl.os_lock call
        real = tl.os_lock

        def watch(*a, **kw):
            self.lock_calls.append(threading.current_thread().name)
            return real(*a, **kw)
        self.real_os_lock = real
        p = mock.patch.object(tl, "os_lock", side_effect=watch)
        p.start()
        self.addCleanup(p.stop)

    # -- harness -----------------------------------------------------------------------------------------------------

    def tracker(self, beads=(), slots=0, cfg=None):
        (self.repo / ".task-loop.json").write_text(json.dumps({"slots": {"count": slots}, "engine": cfg or {}}))
        self.bd = SafeBd(beads, slots=slots)
        tlbd.install(self, self.bd)
        self.cfg = tl.profile_slots(self.repo_s)
        return self.bd

    def together(self, fns):
        """{name: result} of the callables, each in a thread of that name, released by one barrier. A thread's exception is raised here."""
        start, res, errs = threading.Barrier(len(fns), timeout=GUARD), {}, {}

        def go(name, fn):
            try:
                start.wait()
                res[name] = fn()
            except BaseException as e:
                errs[name] = e
        ths = [threading.Thread(target=go, args=(n, f), name=n) for n, f in fns.items()]
        for t in ths:
            t.start()
        for t in ths:
            t.join(GUARD)
        self.assertFalse([t.name for t in ths if t.is_alive()], "a thread hung")
        if errs:
            raise next(iter(errs.values()))
        return res

    def race(self, a_fn, b_fn, arrive=lambda a: claims(a)):
        """A and B together, B starting once A is inside. A is held at its first bd claim until B has reached the guarded step: B's
        call of tl.os_lock or B's own claim (what `arrive` says of a bd call). {"A": .., "B": ..}."""
        arrived, paused, a_in = threading.Event(), [], threading.Event()
        name = lambda: threading.current_thread().name  # noqa: E731

        def before(a):
            if name() == "B" and arrive(a):
                arrived.set()
            if name() == "A" and not paused and claims(a):
                paused.append(1)
                a_in.set()
                if not arrived.wait(GUARD):
                    raise AssertionError("B never reached the guarded step")

        def watch_b(*a, **kw):  # B's call of os_lock is its arrival at the lock
            self.lock_calls.append(name())
            if name() == "B":
                arrived.set()
            return self.real_os_lock(*a, **kw)
        self.bd.before = before
        try:
            with mock.patch.object(tl, "os_lock", side_effect=watch_b):
                return self.together({"A": a_fn, "B": lambda: (a_in.wait(GUARD), b_fn())[1]})  # B comes after A is inside
        finally:
            self.bd.before = lambda a: None

    def hold(self, name, minutes=30, why="shots"):
        return tl.cmd_slot(Args(op="hold", name=name, why=why, for_min=minutes, n=None, bead=None, force=False))

    # -- 1: no bead claimed or run twice ---------------------------------------------------------------------------------

    def test_no_bead_is_claimed_twice(self):
        """Four sessions claim one bead at once: one wins and the rest are told TAKEN; a later claim by anyone is refused too.
        Red when: tl.py cmd_claim, `print("TAKEN")` of the refused claim is followed by `return 0` instead of `return 1`."""
        bd = self.tracker([test_loop.bead("w-1")])
        res = self.together({n: (lambda: tl.cmd_claim(Args(id="w-1", worktree=self.repo_s, slot=None))) for n in "ABCD"})
        self.assertEqual(sorted(res.values()), [0, 1, 1, 1], res)
        (who,) = [a for b, a in bd.won if b == "w-1"]
        self.assertEqual(bd.beads["w-1"]["assignee"], who)
        self.assertEqual(self.out.getvalue().count("CLAIMED w-1"), 1)
        late = tl.cmd_claim(Args(id="w-1", worktree=self.repo_s, slot=None))  # the main thread, a fifth session
        self.assertEqual((late, [a for b, a in bd.won if b == "w-1"]), (1, [who]))
        self.assertEqual(tl.bd_store().ready(), [])  # nothing is left for a loop to pick and run again

    # -- 2: no slot used by two at once, a hold included -----------------------------------------------------------------

    def test_no_slot_is_used_by_two_at_once_a_hold_included(self):
        """One session's loop take and hand run (bd lets it re-claim its own slot bead) race for s1, a hold and a hand run for s2;
        then the hold keeps both off, runs the clock out and frees the slot.
        Red when: tl.py slot_lock body is `return contextlib.nullcontext()` (the slot lock does nothing)."""
        bd = self.tracker(slots=3)
        self.actors.update(A="tl-one", B="tl-one", MainThread="tl-main")
        got = self.race(lambda: tl.take_slot(self.repo_s, self.cfg, "loop"), lambda: tl.take_named_slot(self.repo_s, "s1", self.cfg, "hand"))
        self.assertEqual(got["A"][0], "s1")
        self.assertIsNone(got["B"][0], got)  # refused: the slot is held
        self.assertIn("held by", got["B"][1])
        got = self.race(lambda: self.hold("s2"), lambda: tl.take_named_slot(self.repo_s, "s2", self.cfg, "hand"))
        self.assertEqual(got["A"], 0)
        self.assertIsNone(got["B"][0], got)
        self.assertIn("held by", got["B"][1])
        # the hold stays: no loop take, no hand run, no second hold gets it
        self.assertEqual(tl.take_slot(self.repo_s, self.cfg, "loop")[0], "s3")
        self.assertIsNone(tl.take_slot(self.repo_s, self.cfg, "loop"))  # s1 and s3 used, s2 held
        self.assertIn("held by", tl.take_named_slot(self.repo_s, "s2", self.cfg, "hand")[1])
        self.actors["MainThread"] = "tl-other"
        self.assertEqual(self.hold("s1"), 1)  # a slot in use is never held
        self.assertEqual(self.hold("s2"), 1)  # another session's hold is not taken over
        # the hold runs out on the fake clock: the next take frees it and gets the slot
        self.clock.advance(30 * 60 + 1)
        self.assertEqual(tl.take_slot(self.repo_s, self.cfg, "loop")[0], "s2")
        owners = {b["title"].split()[-1]: b["assignee"] for b in bd.slots.values()}
        self.assertEqual(owners, {"s1": "tl-one", "s2": "tl-other", "s3": "tl-main"})

    # -- 3: no two beads of one area at once -----------------------------------------------------------------------------

    def test_no_two_beads_of_one_area_run_at_once(self):
        """Two runs of one area (a hand run each, --exclusive-area) decide at once: the first in takes the area, the other is refused;
        a bead of another area is not held back.
        Red when: loop.py area_lock, `if not has_areas(cfg):` is `if True:` (the area lock does nothing)."""
        beads = [dict(test_loop.bead(b, labels=["lane:" + area]), status="in_progress") for b, area in
                 (("w-1", "a"), ("w-2", "a"), ("w-3", "b"))]
        bd = self.tracker(beads, slots=3, cfg={"area_label_prefix": "lane:"})
        cfg = cfg_with(area_label_prefix="lane:")
        for s, who in (("sl-1", "A"), ("sl-2", "B"), ("sl-3", "C")):
            bd.slots[s].update(status="in_progress", assignee=who)
        arrived, a_in = threading.Event(), threading.Event()

        class Lock:  # the engine lock of a worktree: A's take is held until B has reached the area decision
            def __init__(self, me):
                self.me = me

            def take(self):
                if self.me == "B":
                    arrived.set()
                elif self.me == "A":
                    a_in.set()
                    if not arrived.wait(GUARD):
                        raise AssertionError("B never reached the area decision")
                return ""

        def run(bead, slot, who):
            return lambda: ((a_in.wait(GUARD) if who == "B" else None),
                            engine.take_area(Args(id=bead, exclusive_area=True), self.repo_s, cfg, Lock(who), sb=slot))[1]

        with mock.patch.object(tl, "os_lock", side_effect=lambda *a, **kw: (arrived.set() if threading.current_thread().name == "B" else None,
                                                                            self.real_os_lock(*a, **kw))[1]):
            got = self.together({"A": run("w-1", "sl-1", "A"), "B": run("w-2", "sl-2", "B")})
        self.assertEqual(got["A"], "", got)
        self.assertIn("area a busy: w-1 in s1", got["B"])
        self.assertIn("(--exclusive-area)", got["B"])
        marked = [s for s, b in bd.slots.items() if (b.get("metadata") or {}).get("held_bead")]
        self.assertEqual(marked, ["sl-1"])
        self.assertEqual(run("w-3", "sl-3", "C")(), "")  # area b is free
        self.assertEqual(sorted(loop.running(self.repo_s).items()), [("w-1", "s1"), ("w-3", "s3")])

    # -- 4: slots served in ticket order ---------------------------------------------------------------------------------

    def test_slots_are_served_in_ticket_order_priority_first(self):
        """Three waiters for one held slot, woken against the line, are served first the lowest priority number, then arrival order;
        a waiter that died drops out of the line.
        Red when: tl.py wait_slot, `if not ahead:` is `if True:` (any woken waiter may take a free slot)."""
        bd = self.tracker(slots=1)
        bd.slots["sl-1"].update(status="in_progress", assignee="owner")
        served, waiters = [], {}

        class Waiter(threading.Thread):
            def __init__(self, name, prio):
                super().__init__(name=name, daemon=True)
                self.prio, self.wake, self.settled, self.got = prio, threading.Event(), threading.Event(), None

            def nap(self, secs):  # the sleep between two looks: parked until the test wakes this waiter
                self.settled.set()
                if not self.wake.wait(GUARD):
                    raise AssertionError("never woken")
                self.wake.clear()

            def run(self):
                try:
                    self.got = tl.wait_slot(test.repo_s, test.cfg, self.name, sleep=self.nap, prio=self.prio)
                finally:
                    self.settled.set()
        test = self
        for name, prio in (("W1", 2), ("W2", 2), ("W3", 0)):  # arrival order W1, W2, W3; W3 is the urgent one
            waiters[name] = Waiter(name, prio)
            waiters[name].start()
            self.assertTrue(waiters[name].settled.wait(GUARD))  # it has its ticket and has looked once
        line = [t["why"] for t in tl.waiting_line(self.repo_s)]
        self.assertEqual(line, ["W3", "W1", "W2"])
        tl.release_slot(self.repo_s, "s1", force=True)  # the owner lets go
        pending = ["W2", "W1", "W3"]  # woken against the line
        while pending:
            for n in pending:
                waiters[n].settled.clear()
                waiters[n].wake.set()
                self.assertTrue(waiters[n].settled.wait(GUARD))
            (done,) = [n for n in pending if waiters[n].got]
            served.append(done)
            pending.remove(done)
            tl.release_slot(self.repo_s, "s1", force=True)
        for w in waiters.values():
            w.join(GUARD)
        self.assertEqual(served, ["W3", "W1", "W2"])
        self.assertEqual(list(tl.ticket_dir(self.repo_s).glob("*.json")), [])
        # a waiter whose process is gone is dropped by whoever reads the line, and blocks nobody
        d = tl.ticket_dir(self.repo_s)
        (d / "000000000099.json").write_text(json.dumps({"seq": 99, "prio": 0, "pid": 5151, "start": "T5151", "why": "dead", "since": 1}))
        self.assertEqual(tl.waiting_line(self.repo_s), [])
        self.assertFalse((d / "000000000099.json").exists())
        self.assertEqual(tl.wait_slot(self.repo_s, self.cfg, "late", stop=lambda: True)[0], "s1")
        # tickets taken at once are all different and numbered in arrival order
        seqs = self.together({"T%d" % i: (lambda: tl.take_ticket(self.repo_s, "x")["seq"]) for i in range(6)})
        self.assertEqual(sorted(seqs.values()), list(range(min(seqs.values()), min(seqs.values()) + 6)))

    # -- 5: no checkout under another process's live engine lock ---------------------------------------------------------

    def test_no_checkout_happens_under_a_live_engine_lock(self):
        """A live engine in a slot's worktree keeps every taker, hold, reset and branch release off it, whatever its slot bead says;
        a dead engine's lock does not.
        Red when: tl.py engine_busy, `lock = read_engine_lock(wt)` is `lock = {}` (every lock reads as no lock)."""
        bd = self.tracker(slots=2)
        self.live.add(OTHER_ENGINE)
        s1, s2 = (tl.slot_dir(self.repo_s, n, self.cfg) for n in ("s1", "s2"))
        tl.write_engine_lock(s1, {"pid": OTHER_ENGINE, "start": "T%d" % OTHER_ENGINE, "bead": "w-9", "started": self.clock.now()})
        self.assertIn("pid %d runs w-9" % OTHER_ENGINE, tl.engine_busy(s1))
        self.assertEqual(bd.slots["sl-1"]["status"], "open")  # the slot bead says free
        self.assertEqual(tl.take_slot(self.repo_s, self.cfg, "loop")[0], "s2")  # a loop passes over s1
        self.assertIn("busy", tl.take_named_slot(self.repo_s, "s1", self.cfg, "hand")[1])
        self.assertEqual(self.hold("s1"), 1)
        self.assertIn("BUSY", self.out.getvalue())
        with mock.patch.object(tl, "git", side_effect=AssertionError("git ran in a live slot")), \
                mock.patch.object(tl, "run_git", side_effect=AssertionError("a checkout ran in a live slot")):
            self.assertEqual(tl.main(["slot", "reset", "s1", "--bead", "w-1"]), 4)  # the reset stops before any git
            self.assertEqual(tl.main(["slot", "release", "s1"]), 1)
        listing = "task/w-9"
        with mock.patch.object(tl, "git", return_value="worktree %s\nHEAD abc\nbranch refs/heads/%s\n\nworktree %s\nHEAD abc\n" % (
                s1, listing, s2)), mock.patch.object(tl, "run_git", side_effect=AssertionError("freed a branch under a live engine")):
            self.assertIn("runs w-9", tl.free_branch(self.repo_s, s2, listing))  # its branch is not taken from it
        self.assertEqual(tl.read_engine_lock(s1)["pid"], OTHER_ENGINE)  # and its lock is still there
        self.live.discard(OTHER_ENGINE)  # the engine died: its lock is no obstacle
        self.assertEqual(tl.engine_busy(s1), "")
        self.assertEqual(tl.take_named_slot(self.repo_s, "s1", self.cfg, "hand")[1], "")

    # -- 6/7: lands and releases, on one lock, against one origin --------------------------------------------------------

    class Origin:
        """origin/main for release.push_main: a head that only a push from the current head moves, and the versions pushed."""

        def __init__(self):
            self.mu = threading.Lock()
            self.head, self.patch, self.versions, self.local, self.log = 0, 0, [], {}, []
            self.inside = self.most = 0

    def releases(self):
        """Two releases bumped on h0 (both 0.1.1) race through release.push_main; whichever pushes first is held in its push until the other has reached the lock.
        -> the Origin."""
        o = self.Origin()
        o.local = {"A": {"base": 0, "version": "0.1.1"}, "B": {"base": 0, "version": "0.1.1"}}
        arrived = threading.Event()
        me = lambda: threading.current_thread().name  # noqa: E731

        def git(repo, *a, check=True):
            if a[:2] == ("remote", "get-url"):
                return "file:///origin.git"
            with o.mu:
                if a == ("rev-parse", "origin/main"):
                    return "h%d" % o.head
                if a[:1] == ("reset",):
                    o.log.append((repo, "reset"))
                    return ""
            raise AssertionError("git %s" % (a,))

        def fetch(repo):
            pass

        def run(cmd, repo, check=True):
            with o.mu:
                loc = o.local[repo]
                if "rebase" in cmd:
                    loc["base"] = o.head
                    o.log.append((repo, "rebase"))
                    return types.SimpleNamespace(returncode=0, stdout="", stderr="")
            assert "push" in cmd, cmd
            with o.mu:
                o.inside += 1
                o.most = max(o.most, o.inside)
            if not o.versions and not arrived.wait(GUARD):  # the first push is held until the other release is at the lock
                raise AssertionError("the other release never reached the lock")
            with o.mu:
                o.inside -= 1
                o.log.append((repo, "push"))
                if loc["base"] != o.head:  # a push from a base that is not origin's head is refused
                    return types.SimpleNamespace(returncode=1, stdout="", stderr="! [rejected] non-fast-forward")
                o.head += 1
                o.patch = int(loc["version"].split(".")[2])
                o.versions.append((repo, loc["version"]))
                o.log.append((repo, "accepted"))
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        def bump(repo, message, minor):  # release.next_version reads origin/main's version
            with o.mu:
                o.local[repo]["version"] = "0.1.%d" % (o.patch + 1)
                o.log.append((repo, "bump"))
                return o.local[repo]["version"]

        calls = []

        def watch(*a, **kw):
            calls.append(me())
            if len(calls) == 2:
                arrived.set()
            return self.real_os_lock(*a, **kw)
        with mock.patch.object(release, "git", side_effect=git), mock.patch.object(release, "fetch", side_effect=fetch), \
                mock.patch.object(release, "run", side_effect=run), mock.patch.object(release, "bump_and_commit", side_effect=bump), \
                mock.patch.object(release, "say"), mock.patch.object(tl, "os_lock", side_effect=watch):
            got = self.together({n: (lambda n=n: release.push_main(n, "race release", False, "0.1.1", "h0")) for n in "AB"})
        o.got = got
        return o

    def test_every_land_holds_the_land_lock_and_is_rebased_and_pushed_once(self):
        """Two engine lands and a release push take one lock per origin: never two inside at once. Two releases built on one base:
        the late one rebases onto what the first pushed, and each release's push is accepted once.
        Red when: engine.py land_lock, `with self.locked("land_lock", path):` is `with contextlib.nullcontext():`; or
        release.py push_main, `if head != base:` is `if False:` (a moved origin/main is not rebased onto)."""
        self.tracker()
        url = "file:///origin.git"
        eng = lambda: types.SimpleNamespace(git=lambda *a: url, wt=self.repo_s,  # noqa: E731 - Engine.land_lock with the parts it reads
                                            locked=lambda what, path: tl.os_lock(path, "bead"))
        mu, inside, most, entered, joined = threading.Lock(), [0], [0], [], threading.Event()

        def section(cm):
            def go():
                with cm:
                    with mu:
                        entered.append(threading.current_thread().name)
                        inside[0] += 1
                        most[0] = max(most[0], inside[0])
                        first = len(entered) == 1
                        if inside[0] > 1:
                            joined.set()
                    if first and not joined.wait(GUARD):  # held until the others have reached the lock (or got in beside us)
                        raise AssertionError("the others never reached the land lock")
                    with mu:
                        inside[0] -= 1
            return go
        calls = []

        def watch(*a, **kw):
            calls.append(threading.current_thread().name)
            if len(calls) == 3:
                joined.set()
            return self.real_os_lock(*a, **kw)
        with mock.patch.object(tl, "os_lock", side_effect=watch):
            self.together({"X": section(engine.Engine.land_lock(eng())), "Y": section(engine.Engine.land_lock(eng())),
                           "Z": section(tl.os_lock(tl.land_lock_path(url), "release: z"))})
        self.assertEqual((most[0], sorted(entered)), (1, ["X", "Y", "Z"]))
        o = self.releases()
        self.assertEqual(o.most, 1)  # never two pushes inside the lock at once
        accepted = [r for r, what in o.log if what == "accepted"]
        self.assertEqual(sorted(accepted), ["A", "B"])  # each release pushed exactly once
        first, second = (r for r, _ in o.versions)
        self.assertEqual([what for r, what in o.log if r == first], ["push", "accepted"])
        late = [what for r, what in o.log if r == second]
        self.assertLess(late.index("rebase"), late.index("accepted"))  # the late one rebased onto the first's push before its own

    def test_every_release_takes_a_distinct_version(self):
        """Two releases bumped on one base (both 0.1.1) end as 0.1.1 and 0.1.2: the one that lost the race bumps again on the new base.
        Red when: release.py push_main, `version = bump_and_commit(repo, message, minor)` inside the `head != base` block is `pass`."""
        self.tracker()
        o = self.releases()
        versions = sorted(v for _, v in o.versions)
        self.assertEqual(versions, ["0.1.1", "0.1.2"])
        self.assertEqual(sorted(o.got.values()), ["0.1.1", "0.1.2"])  # what each release reports is what it pushed

    # -- 8: nothing left held --------------------------------------------------------------------------------------------

    def nothing_held(self, slots):
        for b in self.bd.slots.values():
            self.assertEqual((b["status"], b.get("assignee") or ""), ("open", ""), b)
            self.assertFalse(set(b.get("metadata") or {}) & set(tl.HELD_KEYS), b)
        self.assertEqual(list(tl.ticket_dir(self.repo_s).glob("*.json")), [])
        for n in slots:
            self.assertFalse(tl.engine_lock_path(tl.slot_dir(self.repo_s, n, self.cfg)).exists(), n)
        for lock in (tl.config_dir() / "locks").glob("*.lock"):
            with open(str(lock), "a+") as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises while a holder is left

    def test_nothing_is_left_held_after_everyone_is_done(self):
        """Two loops, a hand run, a waiter and a hold use five slots at once and all let go; then a dead waiter, an expired hold and a
        dead engine's lock are left behind and the next taker clears them.
        Red when: tl.py release_slot_locked, the line `unclaim_slot(repo, b, force)` is `pass` (a released slot stays claimed)."""
        names = ["s%d" % i for i in range(1, 6)]
        bd = self.tracker(slots=5)
        repo, cfg = self.repo_s, self.cfg

        def loop_run(bead):
            def go():
                got = tl.take_slot(repo, cfg, "tl loop", bead=bead)
                if got:
                    tl.loop_lock(got[1], got[0], got[2], bead=bead)
                    tl.drop_engine_lock(got[1], os.getpid())
                    tl.release_slot(repo, got[0], mine=True)
            return go

        def hand():
            sb, why = tl.take_named_slot(repo, "s5", cfg, "hand run")
            if sb:
                tl.release_slot(repo, "s5", mine=True)

        def waiter():
            got = tl.wait_slot(repo, cfg, "waiter", sleep=lambda d: None)  # slots are free soon: no wait to sleep through
            tl.release_slot(repo, got[0], mine=True)

        def holder():
            if self.hold("s4") == 0:
                tl.cmd_slot(Args(op="release", name="s4", force=False))
        self.together({"L1": loop_run("w-1"), "L2": loop_run("w-2"), "H": hand, "W": waiter, "P": holder})
        self.nothing_held(names)
        # left behind by processes that died
        self.actors["MainThread"] = "tl-ghost"
        self.hold("s1", minutes=1)
        self.clock.advance(61)  # the hold has run out
        d2 = tl.slot_dir(repo, "s2", cfg)
        tl.write_engine_lock(d2, {"pid": 5252, "start": "T5252", "bead": "w-3", "started": 1})  # not in the process table
        (tl.ticket_dir(repo) / "000000000077.json").write_text(json.dumps({"seq": 77, "prio": 0, "pid": 5151, "start": "T5151", "why": "dead", "since": 1}))
        self.actors["MainThread"] = "tl-main"
        for name in ("s1", "s2"):
            sb = tl.take_named_slot(repo, name, cfg, "next")[0]
            self.assertTrue(sb, name)  # the expired hold and the dead engine's lock are no obstacle
            tl.release_slot(repo, name, mine=True)
        self.assertEqual(tl.waiting_line(repo), [])
        tl.drop_engine_lock(d2, 5252)
        self.nothing_held(names)


if __name__ == "__main__":
    unittest.main()
