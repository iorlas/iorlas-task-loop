"""The slot verbs of `tl slot`: each takes the env and the parsed arguments, prints what the old verb printed, and returns the
exit code. A SlotFail becomes a code by `fail_code`: busy 4, bead_pinned 5, slot_broken 3 (0 is done, 1 a refusal, 2 a misuse)."""
import os
from typing import Any, Final

from taskloop.app.slots.env import SlotEnv, stamp
from taskloop.app.slots.line import order, waiting_line, wait_slot
from taskloop.app.slots.marks import held_by, mark_held
from taskloop.app.slots.pool import Slot, SlotPool
from taskloop.app.slots.reset import setup
from taskloop.contracts.ports import NewBead
from taskloop.contracts.slots import SlotFail, SlotGitError

CODES: Final = {"busy": 4, "bead_pinned": 5, "slot_broken": 3}


def fail_code(e: SlotFail) -> int:
    return CODES[e.code]


def listing(env: SlotEnv, a: Any) -> int:
    """NAME BEAD STATUS HOLDER WHY ENGINE DIR; then the line, first served first: WAITING N P<priority> WHO WHY SINCE."""
    pool = SlotPool(env)
    with env.take_lock():
        pool.free_expired()
    for s in pool.slots():
        b, hold = s.bead, s.hold()
        held = b.status == "in_progress" or hold
        m = b.metadata
        holder = (m.get("held_by") or b.assignee or "?") if held else "-"
        why = ("%s (hold until %s)" % (hold.why, stamp(hold.until)) if hold else
               "%s since %s" % (m.get("held_why") or "?", m.get("held_since") or "?") if held else "-")
        env.say("\t".join([s.name, b.id, b.status, holder, why, env.busy(s.dir) or "-", s.dir]))
    for n, t in enumerate(waiting_line(env), 1):
        env.say("\t".join(["WAITING", str(n), "P%s" % order(t)[0], "pid %s" % t.pid, t.why or "-", stamp(t.since) if t.since else "-"]))
    return 0


def hold(env: SlotEnv, a: Any) -> int:
    """A slot for something that is no bead (screenshots, a person): the loop and run-task keep off it."""
    if not a.name or not a.why:
        env.warn("tl: tl slot hold NAME --why TEXT [--for MIN]")
        return 1
    pool = SlotPool(env)
    with env.take_lock():
        pool.free_expired()
        b = pool.bead(a.name)
        if b is None:
            env.warn("tl: no slot " + a.name)
            return 1
        s = Slot(pool, a.name, b)
        mine = s.hold()
        busy = env.busy(s.dir)
        if not busy and mine and mine.by != env.actor:
            busy = "held by %s until %s: %s" % (mine.by, stamp(mine.until), mine.why)
        if not busy and not mine and b.status != "open":
            busy = "held by %s" % held_by(b)
        if not busy and b.status == "open" and not s.claimed():
            busy = "claimed by another session just now"
        if busy:  # renewing one's own hold is fine; anything else in use is never held
            env.say("BUSY: slot %s %s" % (a.name, busy))
            return 1
        until = env.now() + float(a.for_min if a.for_min is not None else 60) * 60
        mark_held(env, b.id, a.why, until)
    env.event("slot-hold", "", slot=a.name, slot_bead=b.id, why=a.why, until=until, repo=env.repo)
    env.say("HELD %s until %s: %s" % (a.name, stamp(until), a.why))
    return 0


def init(env: SlotEnv, a: Any) -> int:
    """Once per repo: the slot beads and their worktrees."""
    n = int(a.n or env.cfg.count or 0)
    if n < 1:
        env.warn("tl: slots.count is not set in .task-loop.json")
        return 1
    pool = SlotPool(env)
    have = {b.title.split()[-1] for b in pool.beads()}
    for i in range(1, n + 1):
        name = "s%d" % i
        if name not in have:
            env.store.create(NewBead(title="slot %s %s" % (env.host, name), issue_type="chore", labels=["slot"], priority=4,
                                     description="Slot worktree " + name + " for task-loop. Claimed while a session uses it; never work."))
        d = env.dir_of(name)
        env.exclude_local(env.repo)
        if not os.path.isdir(d):
            try:
                env.git.fetch(env.repo)
                env.git.add_worktree(env.repo, d, env.cfg.base)
            except SlotGitError as e:
                env.warn(e.tail)
                return 1
        env.say(name + "\t" + d)
    return 0


def take(env: SlotEnv, a: Any) -> int:
    """Claim the first free slot, never ahead of a waiter in line; prints NAME DIR BEAD."""
    got = wait_slot(env, "tl slot take", stop=lambda: True)
    env.say("\t".join(got) if got else "NONE")
    return 0 if got else 1


def release(env: SlotEnv, a: Any) -> int:
    pool = SlotPool(env)
    d = env.dir_of(a.name) if a.name else ""
    busy = env.busy(d) if d else ""
    if busy and not a.force:
        env.say("BUSY: slot %s: %s; it frees itself when that run ends (--force: release and drop the lock)" % (a.name, busy))
        return 1
    if busy:
        env.drop_engine_lock(d)
    try:
        pool.slot(a.name).release(force=a.force)
    except SlotFail:
        env.warn("tl: no slot " + str(a.name))
        return 1
    return 0


def reset(env: SlotEnv, a: Any) -> int:
    """Per task: a clean tree on a fresh task branch; ignored setup output stays."""
    try:
        SlotPool(env).named(a.name).ready_for(a.bead or "", force=a.force)
    except SlotFail as e:
        a.error = e.why
        if e.code == "slot_broken":
            env.warn("tl: " + e.why)
        else:
            env.say(("BUSY: " if e.code == "busy" else "TAKEN: ") + e.why)
        return fail_code(e)
    return 0


def run_setup(env: SlotEnv, a: Any) -> int:
    try:
        setup(SlotPool(env).named(a.name), force=True)
    except SlotFail as e:
        env.warn("tl: " + e.why)
        return fail_code(e)
    return 0
