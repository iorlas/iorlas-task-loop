"""The loop: one process runs ready beads one after another, each through `tl run-task` in any free slot."""
import atexit
import contextlib
import datetime
import json
import socket
import time
from dataclasses import dataclass, field
from os import EX_CONFIG
from pathlib import Path

from taskloop.app.loop import verdict as vd
from taskloop.app.loop import waits
from taskloop.app.loop.core import Core, prio_of
from taskloop.app.loop.env import LoopEnv
from taskloop.app.loop.files import LoopFiles
from taskloop.app.loop.queue import Queue, QueueRule, rank_ready
from taskloop.app.loop.refuse import Refuser
from taskloop.app.loop.run import BeadRun, Where
from taskloop.app.loop.settle import Settle
from taskloop.app.loop.take import Taker
from taskloop.app.loop.versions import Installs
from taskloop.app.slots import line as slots_line
from taskloop.app.slots import owned
from taskloop.app.slots.lease import Lease
from taskloop.app.slots.pool import SlotPool
from taskloop.contracts import runlife, wire
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import ConfigError
from taskloop.contracts.ids import BeadId
from taskloop.contracts.loop import LoopState, LoopWait, QueueRow
from taskloop.contracts.parks import ParkStore
from taskloop.contracts.run import LoopLogLine
from taskloop.contracts.slots import SlotFail

SKIPPED_KEPT = 100


@dataclass(frozen=True)
class LoopArgs:
    max_beads: int = 0
    until: str = ""  # HH:MM
    wait_slot_min: float = 30
    wait_drained: bool = False
    pin: bool = False
    only: tuple[str, ...] = ()  # tl loop --only: take just these beads, in this order
    argv: list[str] = field(default_factory=list)  # the loop re-execs itself with these


def end_time(hhmm: str, now: float) -> float:
    """--until HH:MM: the next time it is that o'clock (tomorrow when it has passed today)."""
    if not hhmm:
        return 0.0
    h, m = (int(x) for x in hhmm.split(":"))
    at = datetime.datetime.fromtimestamp(now)
    t = at.replace(hour=h, minute=m, second=0, microsecond=0)
    return (t if t > at else t + datetime.timedelta(days=1)).timestamp()


def parse_handover(raw: str) -> tuple[LoopState | None, str]:
    """(the state an older install of this loop handed over, why it was dropped). A state that cannot be read (an old shape, a
    wrong `v`) is absent: the loop starts a clean pass, and checkpoints and slot leases stay the truth for a bead mid-flight."""
    if not raw:
        return None, ""
    try:
        return wire.load(LoopState, json.loads(raw)), ""
    except ValueError as e:  # msgspec.ValidationError, StaleRecord and bad JSON are ValueErrors
        return None, str(e)[:200]


class Loop(Core):
    def __init__(self, env: LoopEnv, files: LoopFiles, installs: Installs, args: LoopArgs, handover: str = "") -> None:
        inherited, self.dropped = parse_handover(handover)
        super().__init__(env, files, inherited)
        self.installs, self.args = installs, args
        self.until = self.until if inherited else end_time(args.until, env.now())
        self.settle = Settle(env, files, self.tune, self.say, self.c, self.gate, self.net, self.left)
        self.runner = BeadRun(env, files, installs, self.tune, self.stop_mode, self.running, self.beat, self.say)
        self.taker = Taker(env, self.runner, self.tune, self.say, self.record, self.c.later)
        self.refuser = Refuser(env.store, self.say)  # lint refusals: one label and comment per bead, one line per loop
        self.area_wait = [0.0, 0.0]  # when every ready bead began waiting for an area, and when that was last said
        if inherited:
            self.st = LoopState(pid=env.pid, started=self.started, t=env.now(), repo=env.repo, version=env.version, code_dir=env.code_dir,
                                actor=inherited.actor or env.actor())

    # ---- the process -------------------------------------------------------------------------------------------
    def main(self) -> int:
        atexit.register(self.write_exit)
        try:
            self.open_log()
            with self.files.lock():
                self.publish()
                self.files.clean_command()
            if self.dropped:
                self.say(f"warn: the state handed over could not be read ({self.dropped}): dropped, a clean pass starts")
                self.env.event("reload", "", who="loop", old="", new=self.env.version, code_dir=self.env.code_dir,
                               why="handover state dropped: " + self.dropped)
            if self.exit.get("reason") == vd.PROFILE_AHEAD:
                self.say(self.exit["detail"])
                return EX_CONFIG
            self.prune()
            return self.run()
        except (ConfigError, SystemExit) as err:
            if isinstance(err, SystemExit) and err.code != EX_CONFIG:
                self.left("system_exit", str(err))
                raise
            why = vd.profile_ahead(self.env.version, err).why
            self.say(why)
            self.left(vd.PROFILE_AHEAD, why)
            return EX_CONFIG
        except Exception as e:
            self.left("crash", f"{type(e).__name__}: {e}")
            self.fall_back(e)
            raise
        except BaseException as error:
            self.left("signal" if isinstance(error, KeyboardInterrupt) else "system_exit", str(error))
            raise
        finally:
            self.write_exit()
            atexit.unregister(self.write_exit)
            with contextlib.suppress(OSError), self.files.lock():
                self.files.remove(self.env.pid)
                self.files.clean_command()

    def prune(self) -> None:
        """Old run data, merged build trees and release branches go at the start (tl prune); a failure of it never stops the loop."""
        try:
            self.env.prune(self.say)
        except Exception as e:
            self.say(f"warn: prune failed: {type(e).__name__}: {e}"[:300])

    def fall_back(self, err: Exception) -> None:
        """A loop that breaks soon after a move goes back to the install it came from, once, and says so in red."""
        c, env = self.carry_in, self.env
        if not c.back or c.fallback or env.now() - c.moved_at >= self.tune().reload_fallback or not (Path(c.back) / "skills").is_dir():
            return
        why = f"the loop broke {env.now() - c.moved_at:.0f} s after the move: {type(err).__name__}: {err}"[:300]
        self.installs.record_bad(self.installs.mine, why)
        env.event("reload_fallback", "", who="loop", old=env.version, new=Path(c.back).name, why=why)
        self.say(f"RED: task-loop {env.version} broke after the move; going back to {Path(c.back).name}")
        self.carry_in = c.replace(fallback=True)
        self.exec_to(Path(c.back), back=env.code_dir)

    def exec_to(self, d: Path, back: str) -> bool:
        """Exec into the install in `d` with this loop's argv and state. Returns only when the exec itself failed."""
        env = self.env
        self.carry_in = self.carry_in.replace(back=back, moved_at=env.now())
        self.st = self.st.replace(carry=self.carry())
        try:
            env.exec_into(d, list(self.args.argv), json.dumps(wire.dump(self.st)))
        except OSError as e:  # execv itself failed: the loop goes on where it is
            self.say(f"warn: could not move: {e}")
        return False

    # ---- passes ------------------------------------------------------------------------------------------------
    def run(self) -> int:
        for run in runlife.reconcile(self.env.cfgdir, self.env.now()):  # a run whose process is gone is lost once; nobody guesses later
            self.say(f"run {run} is lost: its process is gone and it recorded no end")
        while True:
            code = self.step()
            if code is not None:
                return code

    def refresh(self) -> None:
        """The rule and the loop's constants are read from the base branch's commit, every tick, after a fetch."""
        self.env.fetch()
        self.prof = self.env.profile()

    def ends(self) -> int | None:
        a, c = self.args, self.c
        if self.stop_mode():
            self.say(f"stopped on request after {c.ran} bead(s)")
            self.left("stop_request")
            return 0
        if self.until and self.env.now() >= self.until:
            self.say(f"{a.until} reached after {c.ran} bead(s)")
            self.left("until")
            return 0
        if a.max_beads and c.ran >= a.max_beads:
            self.say(f"{c.ran} bead(s) run (--max-beads)")
            self.left("max_beads")
            return 0
        return None

    def resource_wait(self) -> bool:
        self.prof = self.env.profile()
        wait = waits.blocked(self.env, self.tune()) or self.c.wait
        if wait and wait.probe_at <= self.env.now():
            self.c.wait = None
            wait = waits.blocked(self.env, self.tune())
        self.wait = wait
        if wait is None:
            return False
        self.say(f"WAIT {wait.reason} {wait.fingerprint}: wakes when {wait.wake}")
        self.publish()
        self.nap(max(1, wait.probe_at - self.env.now()), self.until)
        return True

    def net_wait(self) -> bool:
        """True when the network is down and the loop napped: no claim, a probe every net_probe s, the same bead first after."""
        if not self.net.down:
            return False
        probe, now = self.settle.probe, self.env.now()
        if probe is not None and not self.net.poll(probe, now):
            self.nap(max(1.0, self.net.next_probe - now), self.until)
            return True
        self.net.down_since, self.net.next_probe = None, 0.0
        down_s = round(now - self.c.net_down_t)
        self.say(f"network is back after {down_s} s: {', '.join(self.c.net_first) or 'the queue'} first")
        self.env.event("net_up", ",".join(self.c.net_first), who="loop", repo=self.env.repo, down_s=down_s)
        return False

    def step(self) -> int | None:
        """One pass. None: go on to the next."""
        done = self.ends()
        if done is not None:
            return done
        if self.net_wait():
            return None
        if self.resource_wait():
            return None
        self.refresh()
        self.maybe_move()
        self.start_worktree()
        for line in self.env.release_dead():  # a dead run's claims and slots back to ready before the next pick
            self.say(line)
        self.env.chores()
        q, rule = self.queue()
        cands = self.candidates(q)
        if cands:
            self.area_wait[0] = 0.0
            return self.work(cands, rule)
        return self.idle(q)

    def start_worktree(self) -> None:
        """Slots off: the loop works in its session's worktree. The pick and the state that names it, under a lock: two loops
        starting at once never pick one tree."""
        if self.prof.slots.count > 0 or self.wt:
            return
        with self.env.wt_lock(self.files.key):
            self.wt = self.env.start_worktree(self.worktree_name())
            self.publish()

    def worktree_name(self) -> str:
        """The session's worktree (loop-<session>), reused by each loop start; one another live loop of the repo works in gets
        this loop's own: two loops in one tree reset it under each other."""
        env = self.env
        name = env.session_actor[3:]
        taken = {st.worktree for st in self.files.live(but=env.pid)}
        return env.actor()[3:] if owned.loop_path(env.repo, name) in taken else name

    def queue(self) -> tuple[Queue, QueueRule]:
        q, rule = rank_ready(self.env, self.prof.engine, self.say, self.args.only)
        for s in q.skipped:
            if s.of is not None:
                self.refuser.refuse(s.of, s.skip.why)
        self.set_rows(q)
        return q, rule

    def set_rows(self, q: Queue) -> None:
        now = self.env.now()
        rows = [QueueRow(bead=r.bead.id, prio=prio_of(r.bead), since=self.first_seen.setdefault(r.bead.id, now), ahead=i,
                         reason=r.reason, title=r.bead.title[:100]) for i, r in enumerate(q.ranked)]
        rows += [QueueRow(bead=s.bead, prio=2, since=self.first_seen.setdefault(s.bead, now), ahead=-1, skip=s.skip)
                 for s in q.skipped[:SKIPPED_KEPT]]
        self.rows = rows
        self.publish()

    def candidates(self, q: Queue) -> list[Bead]:
        c, now = self.c, self.env.now()
        for rested, due in self.files.rests().items():  # another loop's pre-engine failure rests the bead here too
            c.later[rested] = max(c.later.get(rested, 0), due)
        for row in q.ranked:
            rec = ParkStore(self.env.cfgdir).get(row.bead.id)
            if rec and rec.reason and rec.permanence == "transient":
                c.later[row.bead.id] = rec.retry_at
                self.gate.held.pop(row.bead.id, None)
        cands = [r.bead for r in q.ranked if c.later.get(r.bead.id, 0) <= now and self.gate.ready(r.bead.id)]
        cands.sort(key=lambda b: b.id not in c.net_first)  # a bead the network paused goes first, the same one (stable sort)
        if cands and cands[0].id not in c.net_first:
            c.net_first = []
        return cands

    def idle(self, q: Queue) -> int | None:
        env, c = self.env, self.c
        retries = [s.skip.until for s in q.skipped if s.skip.kind == "parked" and s.skip.until is not None]
        if q.ranked or retries:
            wakes = [self.gate.next_look(r.bead.id) if r.bead.id in self.gate.held and c.later.get(r.bead.id, 0) <= env.now()
                     else c.later[r.bead.id] for r in q.ranked]
            wake = min([*wakes, *retries])
            self.say("every ready bead waits for a lane or another session: looking again at "
                     + time.strftime("%H:%M:%S", time.localtime(wake)))
            self.wait = LoopWait(reason="no_lane", wake="role usable or retry due", probe_at=wake)
            self.publish()
            delay = max(1, wake - env.now())
            self.nap(min(self.tune().gate_cache, delay) if self.gate.held else delay, self.until)
            return None
        areas = q.areas()
        if areas:  # not drained: those beads run once their area frees; --until still ends the loop
            top = areas[0].skip
            self.wait_area([s.skip.why for s in areas[:3]], top.area, top.holder, top.where)
            return None
        self.area_wait[0] = 0.0
        if not self.args.wait_drained:
            print(f"DRAINED: no ready bead after {c.ran} bead(s)")
            self.left("drained")
            return 0
        self.nap(self.tune().drained_poll, self.until)
        return None

    def wait_area(self, whys: list[str], area: str, holder: str, where: str) -> None:
        t, tune = self.env.now(), self.tune()
        if not self.area_wait[0]:
            self.area_wait[0] = self.area_wait[1] = t
            self.say(f"every ready bead waits for its area ({'; '.join(whys)}): looking again in {tune.area_poll:g} s")
        elif t - self.area_wait[1] >= tune.area_say:  # a hung but live holder never frees it: say how long
            self.area_wait[1] = t
            self.say(f"waiting {(t - self.area_wait[0]) // 60:.0f} min on area {area} held by {holder} in {where}")
        self.nap(tune.area_poll, self.until)

    def acquire(self, prio: int) -> tuple[str, str, BeadId] | None:
        """(name, dir, slot bead) of a free slot, waiting in the repo's slot line (lowest priority number first, then first come)
        with backoff while none is; None on a stop or the end time."""
        env, wait = self.env, self.args.wait_slot_min
        since, told = env.now(), [0.0]

        def waiting(ahead: int) -> None:
            if not told[0] or env.now() - told[0] >= wait * 60:
                where = f" for this loop: {ahead} ahead in line" if ahead else ""
                self.say(f"no free slot{where}{'' if not told[0] else f' for {(env.now() - since) // 60:.0f} min'}; waiting")
                told[0] = env.now()
        return slots_line.wait_slot(env.slot_env(), "tl loop",
                                    stop=lambda: bool(self.stop_mode() or (self.until and env.now() >= self.until)),
                                    sleep=lambda secs: self.nap(secs, self.until), poll=(5, min(30, max(5, wait * 60))),
                                    on_wait=waiting, prio=prio)

    def work(self, cands: list[Bead], rule: QueueRule) -> int | None:
        env, slots = self.env, self.prof.slots.count > 0
        pool = SlotPool(env.slot_env()) if slots else None
        got = self.acquire(min(prio_of(b) for b in cands)) if slots else ("", self.wt, None)
        if got is None:
            return None
        name, d, slot_bead = got
        lease = Lease(env.store, slot_bead, every=self.tune().heartbeat).start()
        try:
            env.loop_lock(d, name, slot_bead, "")  # from the take through reset: no hand run gets in
            if slots:
                cands = self.settle.candidates(name, cands)
            taken = self.taker.attempt_all(cands, Where(name, d, slot_bead, self.started), slots, self.prof.engine, rule, lease)
        finally:
            lease.stop()
            env.drop_engine_lock(d)
            if slots:
                self.release(name, pool)
            self.running(None)
        if taken.verdict is None:  # every candidate is held by another session: the next pass sleeps until one is due
            return None
        return self.settle.apply(taken.verdict, taken.bead, name, slots)

    def release(self, name: str, pool: SlotPool | None = None) -> None:
        with contextlib.suppress(SlotFail):
            (pool or SlotPool(self.env.slot_env())).slot(name).release(mine=True)

    def record(self, bead: str, slot: str, v: vd.Verdict) -> None:
        env = self.env
        self.files.log_line(LoopLogLine(
            t=env.now(), bead=bead, host=socket.gethostname(), slot=slot, outcome=v.outcome,
            minutes=v.minutes or 0.0, rounds=v.rounds or 0, tests_added=v.tests_added or 0, asked=v.asked, run_id=v.run or "",
            engine_log=v.log or "", run_log=v.run_log, why=v.why[:300]))
        self.say(f"{bead} {v.outcome}{': ' + v.why[:160] if v.why else ''}")

    def maybe_move(self) -> None:
        """Between beads: exec the target install with the loop's own argv and state. The pid stays, so what is keyed by it
        (slot line, state file) carries over. Nothing is tested first: a loop that breaks soon after goes back (fall_back)."""
        a, env, c = self.args, self.env, self.c
        if a.pin or not a.argv:
            return
        found = self.installs.move_to()  # a version a run broke in soon after the move is skipped (bad-versions.json)
        gone = self.installs.dangling
        if gone and f"missing:{gone}" not in c.warned:  # once per loop run (the carry keeps it across a move), not per pass
            c.warned.append(f"missing:{gone}")
            self.say(f"warn: installed_plugins.json names {gone}, its directory is missing; falling back to the highest directory")
            env.event("install_missing", "", who="loop", version=gone, running=env.version, target=found.version if found else "")
        if not found:
            return
        self.say(f"moving to {found.version} (was {env.version})")
        env.event("reload", "", who="loop", old=env.version, new=found.version, code_dir=str(found.dir))
        self.exec_to(found.dir, back=str(self.installs.root))
