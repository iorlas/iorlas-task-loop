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
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest import mock

import support.paths  # noqa: F401
from support.shells import quiet_shell

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # python3 -m unittest tests.test_race_invariants, from the repo root
from loop import test_loop

# isort: split
import tl
from support import gitsim, tlbd
from support import slots as sl
from support.builders import cfg_with
from support.engine_locks import put_lock
from support.fake_clock import FakeClock
from support.narrow import must
from support.rebind import rebind
from support.spawn import real_spawner

from taskloop.adapters import (
    beadtools,
    ident,
    landlock,
    pidcheck,
)
from taskloop.adapters import (
    git as git_adapter,
)
from taskloop.app.land.lander import lander_over
from taskloop.app.release import push as release_push
from taskloop.app.run import (
    entry,
    running,
)
from taskloop.app.slots import engine_lock, marks, reset
from taskloop.app.track import (
    trail,
    verbs,
)
from taskloop.app.wire import slots as wslots
from taskloop.contracts.env import snapshot
from taskloop.contracts.gitfacts import GitOutcome, LogRow
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import Git
from taskloop.contracts.slots import Checkout, SlotGitError

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

GUARD = 60  # hang guard only, seconds: no assertion reads a duration
OTHER_ENGINE = 4242  # a pid the fake process table says is alive, and not ours
Args = entry.Args


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
            if a[0] == "update" and "--claim" in a and b and was == "in_progress" and b.get("assignee") == ident.actor():
                return mock.Mock(returncode=0, stdout="", stderr="")
            r = super().__call__(*a, cwd=cwd, check=check)
            if b and was != "in_progress" and b.get("status") == "in_progress":
                self.won.append((a[1], ident.actor()))
            return r


def claims(a):
    return a[:1] == ("update",) and "--claim" in a


@unittest.skipIf(os.name == "nt", "fcntl locks (tl has none on Windows: documented no-op)")
class Invariants(test_loop.Base):
    def setUp(self):
        super().setUp()
        self.clock = FakeClock(1_800_000_000.0)
        self.live = {os.getpid()}  # the fake process table: a pid in it is alive
        self.actors = {}  # thread name -> actor name (default: the thread's name)
        self.out = io.StringIO()
        rebind(self, trail.now, self.clock.now)
        rebind(self, ident.actor, lambda: self.actors.get(threading.current_thread().name, threading.current_thread().name))
        rebind(self, pidcheck.proc_alive, lambda pid, start="": int(pid) in self.live)
        rebind(self, pidcheck.proc_start, lambda pid: f"T{pid}")
        gitsim.reset()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        sim = gitsim.Sim(self)
        sim.install(stack)  # the port's own git calls (RealGit) are answered in process: no repo here, so they find nothing
        p = mock.patch.object(sys, "stdout", self.out)
        p.start()
        self.addCleanup(p.stop)
        self.repo_s = str(self.repo)
        self.lock_calls = []  # (thread name) of every landlock.os_lock call
        real = landlock.os_lock

        def watch(*a, **kw):
            self.lock_calls.append(threading.current_thread().name)
            return real(*a, **kw)
        self.real_os_lock = real
        rebind(self, landlock.os_lock, watch)

    @contextlib.contextmanager
    def watching(self, watch):
        """Every lock taken in the process goes through `watch` for the length of a `with` (it ends in the lock held at setUp)."""
        current = landlock.os_lock
        for mod in list(sys.modules.values()):
            for name, val in list(getattr(mod, "__dict__", {}).items()):
                if val is current:
                    setattr(mod, name, watch)
        try:
            yield
        finally:
            for mod in list(sys.modules.values()):
                for name, val in list(getattr(mod, "__dict__", {}).items()):
                    if val is watch:
                        setattr(mod, name, current)

    # -- harness -----------------------------------------------------------------------------------------------------

    def tracker(self, beads=(), slots=0, cfg=None):
        (self.repo / ".task-loop.json").write_text(json.dumps({"slots": {"count": slots}, "engine": cfg or {}}))
        self.bd = SafeBd(beads, slots=slots)
        tlbd.install(self, self.bd)
        self.cfg = wslots.profile_slots(self.repo_s)
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

    def race(self, a_fn, b_fn, arrive=claims):
        """A and B together, B starting once A is inside. A is held at its first bd claim until B has reached the guarded step: B's
        call of landlock.os_lock or B's own claim (what `arrive` says of a bd call). {"A": .., "B": ..}."""
        arrived, paused, a_in = threading.Event(), [], threading.Event()
        def name():
            return threading.current_thread().name

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
            with self.watching(watch_b):
                return self.together({"A": a_fn, "B": lambda: (a_in.wait(GUARD), b_fn())[1]})  # B comes after A is inside
        finally:
            self.bd.before = lambda a: None

    def hold(self, name, minutes=30, why="shots"):
        return tl.v_slot(
            Args(op="hold", name=name, why=why, for_min=minutes, n=None, bead=None, force=False),
            tl.Ctx(tl.HERE, self.clock.now, [], snapshot(), spawner=real_spawner())
        )

    # -- 1: no bead claimed or run twice ---------------------------------------------------------------------------------

    def test_no_bead_is_claimed_twice(self):
        """Four sessions claim one bead at once: one wins and the rest are told TAKEN; a later claim by anyone is refused too.
        Red when: tl.py cmd_claim, `print("TAKEN")` of the refused claim is followed by `return 0` instead of `return 1`."""
        bd = self.tracker([test_loop.bead("w-1")])
        res = self.together({n: (lambda: verbs.claim(BeadId("w-1"), self.repo_s, None)) for n in "ABCD"})
        self.assertEqual(sorted(res.values()), [0, 1, 1, 1], res)
        (who,) = [a for b, a in bd.won if b == "w-1"]
        self.assertEqual(bd.beads["w-1"]["assignee"], who)
        self.assertEqual(self.out.getvalue().count("CLAIMED w-1"), 1)
        late = verbs.claim(BeadId("w-1"), self.repo_s, None)  # the main thread, a fifth session
        self.assertEqual((late, [a for b, a in bd.won if b == "w-1"]), (1, [who]))
        self.assertEqual(beadtools.bd_store().ready(), [])  # nothing is left for a loop to pick and run again

    # -- 2: no slot used by two at once, a hold included -----------------------------------------------------------------

    def test_no_slot_is_used_by_two_at_once_a_hold_included(self):
        """One session's loop take and hand run (bd lets it re-claim its own slot bead) race for s1, a hold and a hand run for s2;
        then the hold keeps both off, runs the clock out and frees the slot.
        Red when: tl.py slot_lock body is `return contextlib.nullcontext()` (the slot lock does nothing)."""
        bd = self.tracker(slots=3)
        self.actors.update(A="tl-one", B="tl-one", MainThread="tl-main")
        got = self.race(
            lambda: sl.take_slot(self.repo_s, self.cfg, "loop"), lambda: wslots.take_named_slot(self.repo_s, "s1", self.cfg, "hand",
                spawner=real_spawner())
        )
        self.assertEqual(got["A"][0], "s1")
        self.assertIsNone(got["B"][0], got)  # refused: the slot is held
        self.assertIn("held by", got["B"][1])
        got = self.race(lambda: self.hold("s2"), lambda: wslots.take_named_slot(self.repo_s, "s2", self.cfg, "hand",
            spawner=real_spawner()))
        self.assertEqual(got["A"], 0)
        self.assertIsNone(got["B"][0], got)
        self.assertIn("held by", got["B"][1])
        # the hold stays: no loop take, no hand run, no second hold gets it
        self.assertEqual(must(sl.take_slot(self.repo_s, self.cfg, "loop"))[0], "s3")
        self.assertIsNone(sl.take_slot(self.repo_s, self.cfg, "loop"))  # s1 and s3 used, s2 held
        self.assertIn("held by", wslots.take_named_slot(self.repo_s, "s2", self.cfg, "hand", spawner=real_spawner())[1])
        self.actors["MainThread"] = "tl-other"
        self.assertEqual(self.hold("s1"), 1)  # a slot in use is never held
        self.assertEqual(self.hold("s2"), 1)  # another session's hold is not taken over
        # the hold runs out on the fake clock: the next take frees it and gets the slot
        self.clock.advance(30 * 60 + 1)
        self.assertEqual(must(sl.take_slot(self.repo_s, self.cfg, "loop"))[0], "s2")
        owners = {b["title"].split()[-1]: b["assignee"] for b in bd.slots.values()}
        self.assertEqual(owners, {"s1": "tl-one", "s2": "tl-other", "s3": "tl-main"})

    # -- 3: no two beads of one area at once -----------------------------------------------------------------------------

    def test_no_two_beads_of_one_area_run_at_once(self):
        """Two runs of one area (a hand run each, --exclusive-area) decide at once: the first in takes the area, the other is refused;
        a bead of another area is not held back.
        Red when: Taker.claimed (app/loop/take.py) takes the area lock only `if False` (the area lock does nothing)."""
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
                            entry.take_area(Args(id=bead, exclusive_area=True), self.repo_s, cfg, Lock(who), sb=slot))[1]

        real_hold = running.hold_path

        def hold(*a, **kw):  # B reaches the area decision when it asks for the area lock
            if threading.current_thread().name == "B":
                arrived.set()
            return real_hold(*a, **kw)
        with mock.patch.object(running, "hold_path", hold):
            got = self.together({"A": run("w-1", "sl-1", "A"), "B": run("w-2", "sl-2", "B")})
        self.assertEqual(got["A"], "", got)
        self.assertIn("area a busy: w-1 in s1", got["B"])
        self.assertIn("(--exclusive-area)", got["B"])
        marked = [s for s, b in bd.slots.items() if (b.get("metadata") or {}).get("held_bead")]
        self.assertEqual(marked, ["sl-1"])
        self.assertEqual(run("w-3", "sl-3", "C")(), "")  # area b is free
        self.assertEqual(sorted(running.running(self.repo_s).items()), [("w-1", "s1"), ("w-3", "s3")])

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
                self.prio, self.wake, self.settled = prio, threading.Event(), threading.Event()
                self.got: tuple[str, str, str] | None = None

            def nap(self, secs):  # the sleep between two looks: parked until the test wakes this waiter
                self.settled.set()
                if not self.wake.wait(GUARD):
                    raise AssertionError("never woken")
                self.wake.clear()

            def run(self):
                try:
                    self.got = wslots.wait_slot(test.repo_s, test.cfg, self.name, sleep=self.nap, prio=self.prio, spawner=real_spawner())
                finally:
                    self.settled.set()
        test = self
        for name, prio in (("W1", 2), ("W2", 2), ("W3", 0)):  # arrival order W1, W2, W3; W3 is the urgent one
            waiters[name] = Waiter(name, prio)
            waiters[name].start()
            self.assertTrue(waiters[name].settled.wait(GUARD))  # it has its ticket and has looked once
        line = [t.why for t in wslots.waiting_line(self.repo_s)]
        self.assertEqual(line, ["W3", "W1", "W2"])
        wslots.release_slot(self.repo_s, "s1", force=True, spawner=real_spawner())  # the owner lets go
        pending = ["W2", "W1", "W3"]  # woken against the line
        while pending:
            for n in pending:
                waiters[n].settled.clear()
                waiters[n].wake.set()
                self.assertTrue(waiters[n].settled.wait(GUARD))
            (done,) = [n for n in pending if waiters[n].got]
            served.append(done)
            pending.remove(done)
            wslots.release_slot(self.repo_s, "s1", force=True, spawner=real_spawner())
        for w in waiters.values():
            w.join(GUARD)
        self.assertEqual(served, ["W3", "W1", "W2"])
        self.assertEqual(list(sl.ticket_dir(self.repo_s).glob("*.json")), [])
        # a waiter whose process is gone is dropped by whoever reads the line, and blocks nobody
        d = sl.ticket_dir(self.repo_s)
        (d / "000099.json").write_text(json.dumps({"v": 1, "seq": 99, "prio": 0, "pid": sl.dead_pid(), "why": "dead", "since": 1}))
        self.assertEqual(wslots.waiting_line(self.repo_s), [])
        self.assertFalse((d / "000099.json").exists())
        self.assertEqual(must(wslots.wait_slot(self.repo_s, self.cfg, "late", stop=lambda: True, spawner=real_spawner()))[0], "s1")
        # tickets taken at once are all different and numbered in arrival order
        seqs = self.together({f"T{i}": (lambda: sl.take_ticket(self.repo_s, "x").seq) for i in range(6)})
        self.assertEqual(sorted(seqs.values()), list(range(min(seqs.values()), min(seqs.values()) + 6)))

    # -- 5: no checkout under another process's live engine lock ---------------------------------------------------------

    def test_no_checkout_happens_under_a_live_engine_lock(self):
        """A live engine in a slot's worktree keeps every taker, hold, reset and branch release off it, whatever its slot bead says;
        a dead engine's lock does not.
        Red when: tl.py engine_busy, `lock = read_engine_lock(wt)` is `lock = {}` (every lock reads as no lock)."""
        bd = self.tracker(slots=2)
        self.live.add(OTHER_ENGINE)
        s1, s2 = (wslots.slot_dir(self.repo_s, n, self.cfg) for n in ("s1", "s2"))
        put_lock(
            s1, {"pid": OTHER_ENGINE, "start": f"T{int(OTHER_ENGINE)}", "bead": "w-9", "started": self.clock.now()}
        )
        self.assertIn(f"pid {int(OTHER_ENGINE)} runs w-9", engine_lock.engine_busy(s1))
        self.assertEqual(bd.slots["sl-1"]["status"], "open")  # the slot bead says free
        self.assertEqual(must(sl.take_slot(self.repo_s, self.cfg, "loop"))[0], "s2")  # a loop passes over s1
        self.assertIn("busy", wslots.take_named_slot(self.repo_s, "s1", self.cfg, "hand", spawner=real_spawner())[1])
        self.assertEqual(self.hold("s1"), 1)
        self.assertIn("BUSY", self.out.getvalue())
        with mock.patch.object(git_adapter.RealGit, "_run", side_effect=AssertionError("git ran in a live slot")):
            self.assertEqual(self.main(["slot", "reset", "s1", "--bead", "w-1"]), 4)  # the reset stops before any git
            self.assertEqual(self.main(["slot", "release", "s1"]), 1)
        listing = "task/w-9"
        listed = [Checkout(path=s1, branch=listing, main=False), Checkout(path=s2, branch="", main=False)]
        with mock.patch.object(git_adapter.RealGit, "checkouts", return_value=listed):  # any other git call would find the same text
            self.assertIn(
                "runs w-9", reset.free_branch(sl.pool(self.repo_s, cfg=self.cfg).named("s2"), listing)
            )  # its branch is not taken from it
        self.assertEqual(getattr(engine_lock.read_engine_lock(s1), "pid", None), OTHER_ENGINE)  # and its lock is still there
        self.live.discard(OTHER_ENGINE)  # the engine died: its lock is no obstacle
        self.assertEqual(engine_lock.engine_busy(s1), "")
        self.assertEqual(wslots.take_named_slot(self.repo_s, "s1", self.cfg, "hand", spawner=real_spawner())[1], "")

    # -- 6/7: lands and releases, on one lock, against one origin --------------------------------------------------------

    class Origin:
        """origin/main for release.push_main: a head that only a push from the current head moves, and the versions pushed."""

        def __init__(self):
            self.mu = threading.Lock()
            self.head, self.patch, self.versions, self.local, self.log = 0, 0, [], {}, []
            self.inside = self.most = 0
            self.got: dict[str, Any] = {}

        def bump(self, repo):  # flow.next_version reads origin/main's version
            with self.mu:
                self.local[repo]["version"] = f"0.1.{int(self.patch + 1)}"
                self.log.append((repo, "bump"))
                return self.local[repo]["version"]

    class OriginGit:
        """The Git port as push_main uses it: origin/main is `self.o.head`, a push from a base that is not the head is refused."""

        def __init__(self, o, arrived):
            self.o, self.arrived = o, arrived

        def remote_url(self, d, remote):
            return "file:///origin.git"

        def fetch(self, d):
            pass

        def rev_parse(self, d, rev):
            assert rev == "origin/main", rev
            with self.o.mu:
                return f"h{int(self.o.head)}"

        def reset(self, d, rev, mode="mixed"):
            with self.o.mu:
                self.o.log.append((d, "reset"))

        def log(self, d, include, exclude=None, limit=0, grep=""):  # the release commit's subject: "<version>: <message>"
            with self.o.mu:
                return [LogRow(oid="x", time=0, subject=f"{self.o.local[d]['version']}: race release")]

        def rebase(self, d, onto, update_refs=True):
            with self.o.mu:
                self.o.local[d]["base"] = self.o.head
                self.o.log.append((d, "rebase"))
            return GitOutcome(ok=True)

        def rebase_abort(self, d):
            raise AssertionError("no rebase fails here")

        def push(self, d, remote, refspec):
            with self.o.mu:
                loc = self.o.local[d]
                self.o.inside += 1
                self.o.most = max(self.o.most, self.o.inside)
            if not self.o.versions and not self.arrived.wait(GUARD):  # the first push is held until the other release is at the lock
                raise AssertionError("the other release never reached the lock")
            with self.o.mu:
                self.o.inside -= 1
                self.o.log.append((d, "push"))
                if loc["base"] != self.o.head:  # a push from a base that is not origin's head is refused
                    raise SlotGitError("! [rejected] non-fast-forward")
                self.o.head += 1
                self.o.patch = int(loc["version"].split(".")[2])
                self.o.versions.append((d, loc["version"]))
                self.o.log.append((d, "accepted"))

    def releases(self):
        """Two releases bumped on h0 (both 0.1.1) race through release.push_main; whichever pushes first is held in its push until the
        other has reached the lock.
        -> the Origin."""
        o = self.Origin()
        o.local = {"A": {"base": 0, "version": "0.1.1"}, "B": {"base": 0, "version": "0.1.1"}}
        arrived = threading.Event()
        def me():
            return threading.current_thread().name

        calls = []

        def watch(*a, **kw):
            calls.append(me())
            if len(calls) == 2:
                arrived.set()
            return self.real_os_lock(*a, **kw)
        sh = replace(quiet_shell(), port=cast(Git, self.OriginGit(o, arrived)))
        with self.watching(watch):
            got = self.together(
                {n: (lambda n=n: release_push.push_main(Path(n), "race release", "0.1.1", "h0", lambda: o.bump(n), sh)) for n in "AB"}
            )
        o.got = got
        return o

    def test_every_land_holds_the_land_lock_and_is_rebased_and_pushed_once(self):
        """Two engine lands and a release push take one lock per origin: never two inside at once. Two releases built on one base:
        the late one rebases onto what the first pushed, and each release's push is accepted once.
        Red when: land.py Lander.lock, `with self.locked("land_lock", path):` is `with contextlib.nullcontext():`; or
        release/push.py push_main, `if head != base:` is `if False:` (a moved origin/main is not rebased onto)."""
        self.tracker()
        url = "file:///origin.git"
        def eng():
            return types.SimpleNamespace(land_lock_path=lambda: landlock.land_lock_path(url),
                                                    waits=types.SimpleNamespace(locked=lambda what, path: landlock.os_lock(path, "bead")))
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
        with self.watching(watch):
            self.together({"X": section(lander_over(eng()).lock()), "Y": section(lander_over(eng()).lock()),
                           "Z": section(landlock.os_lock(landlock.land_lock_path(url), "release: z"))})
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
        Red when: release/push.py push_main, `version = bump()` inside the `head != base` block is `pass`."""
        self.tracker()
        o = self.releases()
        versions = sorted(v for _, v in o.versions)
        self.assertEqual(versions, ["0.1.1", "0.1.2"])
        self.assertEqual(sorted(o.got.values()), ["0.1.1", "0.1.2"])  # what each release reports is what it pushed

    # -- 8: nothing left held --------------------------------------------------------------------------------------------

    def nothing_held(self, slots):
        for b in self.bd.slots.values():
            self.assertEqual((b["status"], b.get("assignee") or ""), ("open", ""), b)
            self.assertFalse(set(b.get("metadata") or {}) & set(marks.HELD_KEYS), b)
        self.assertEqual(list(sl.ticket_dir(self.repo_s).glob("*.json")), [])
        for n in slots:
            self.assertFalse(engine_lock.engine_lock_path(wslots.slot_dir(self.repo_s, n, self.cfg)).exists(), n)
        for lock in (ident.config_dir() / "locks").glob("*.lock"):
            with open(str(lock), "a+") as f:
                must(fcntl).flock(f, must(fcntl).LOCK_EX | must(fcntl).LOCK_NB)  # raises while a holder is left

    def test_nothing_is_left_held_after_everyone_is_done(self):
        """Two loops, a hand run, a waiter and a hold use five slots at once and all let go; then a dead waiter, an expired hold and a
        dead engine's lock are left behind and the next taker clears them.
        Red when: tl.py release_slot_locked, the line `unclaim_slot(repo, b, force)` is `pass` (a released slot stays claimed)."""
        names = [f"s{i}" for i in range(1, 6)]
        self.tracker(slots=5)
        repo, cfg = self.repo_s, self.cfg

        def loop_run(bead):
            def go():
                got = sl.take_slot(repo, cfg, "tl loop", bead=bead)
                if got:
                    engine_lock.loop_lock(got[1], got[0], got[2], bead=bead)
                    engine_lock.drop_engine_lock(got[1], os.getpid())
                    wslots.release_slot(repo, got[0], mine=True, spawner=real_spawner())
            return go

        def hand():
            sb, _why = wslots.take_named_slot(repo, "s5", cfg, "hand run", spawner=real_spawner())
            if sb:
                wslots.release_slot(repo, "s5", mine=True, spawner=real_spawner())

        def waiter():
            got = wslots.wait_slot(repo, cfg, "waiter", sleep=lambda d: None,
                spawner=real_spawner())  # slots are free soon: no wait to sleep through
            assert got
            wslots.release_slot(repo, got[0], mine=True, spawner=real_spawner())

        def holder():
            if self.hold("s4") == 0:
                tl.v_slot(Args(op="release", name="s4", force=False), tl.Ctx(tl.HERE, self.clock.now, [], snapshot(),
                    spawner=real_spawner()))
        self.together({"L1": loop_run("w-1"), "L2": loop_run("w-2"), "H": hand, "W": waiter, "P": holder})
        self.nothing_held(names)
        # left behind by processes that died
        self.actors["MainThread"] = "tl-ghost"
        self.hold("s1", minutes=1)
        self.clock.advance(61)  # the hold has run out
        d2 = wslots.slot_dir(repo, "s2", cfg)
        put_lock(d2, {"pid": 5252, "start": "T5252", "bead": "w-3", "started": 1})  # not in the process table
        (sl.ticket_dir(repo) / "000077.json").write_text(
            json.dumps({"v": 1, "seq": 77, "prio": 0, "pid": sl.dead_pid(), "why": "dead", "since": 1})
        )
        self.actors["MainThread"] = "tl-main"
        for name in ("s1", "s2"):
            sb = wslots.take_named_slot(repo, name, cfg, "next", spawner=real_spawner())[0]
            self.assertTrue(sb, name)  # the expired hold and the dead engine's lock are no obstacle
            wslots.release_slot(repo, name, mine=True, spawner=real_spawner())
        self.assertEqual(wslots.waiting_line(repo), [])
        engine_lock.drop_engine_lock(d2, 5252)
        self.nothing_held(names)


if __name__ == "__main__":
    unittest.main()
