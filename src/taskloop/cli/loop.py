"""`tl next`, `tl loop [status]`, `tl stop`: tl.py parses, app/launch/loop.py builds the env; this prints and runs."""
import json
import signal
import threading
import time
from typing import Any

from taskloop.app.loop.env import LoopEnv
from taskloop.app.loop.files import LoopFiles
from taskloop.app.loop.health import loop_health
from taskloop.app.loop.loop import Loop, LoopArgs
from taskloop.app.loop.queue import rank_ready
from taskloop.app.loop.versions import Installs
from taskloop.contracts.loop import LoopState


def cmd_next(env: LoopEnv, a: Any) -> int:
    env.fetch()
    q, _ = rank_ready(env, env.profile().engine)
    ranked, skipped = q.ranked, q.skipped
    if a.json:
        print(json.dumps({"pick": ranked[0].bead.to_dict() if ranked else None, "reason": ranked[0].reason if ranked else "",
                          "next": [{"id": r.bead.id, "priority": r.bead.priority, "reason": r.reason} for r in ranked[1:6]],
                          "skipped": [{"id": s.bead, "why": s.skip.why} for s in skipped]}, ensure_ascii=False))
        return 0 if ranked else 1
    if not ranked:
        print("NONE: no ready bead in the queue")
    for n, r in enumerate(ranked[:6]):
        print(f"{'NEXT' if n == 0 else 'then'} {r.bead.id}  P{r.bead.priority}  {r.bead.title[:70]}  ({r.reason})")
    for s in skipped:
        print(f"skip {s.bead}: {s.skip.why}")
    return 0 if ranked else 1


def cmd_stop(env: LoopEnv, files: LoopFiles, a: Any) -> int:
    """Every loop running on the repo stops (a loop started later does not read this command)."""
    loops = files.request_stop(bool(a.now), env.actor())
    if not loops:
        print(f"no loop running on {env.repo}")
        return 1
    for st in loops:
        print(f"STOP {'NOW' if a.now else 'after the current bead'}: loop pid {st.pid}" + (f", running {st.bead}" if st.bead else ""))
    return 0


def ago(now: float, t: float) -> str:
    return f"{(now - t) // 60:.0f} min ago"


def health_lines(env: LoopEnv, files: LoopFiles, loops: list[LoopState]) -> list[str]:
    """Under the loop list: how long since the last beat, the last exit reason, and one RED line for an absent loop."""
    beats = [st.t or st.started for st in loops]
    last = files.last_exit()
    if not beats:
        beats = [st.t or st.started for st in files.died()]
        beats.append(float(str(last.get("t") or 0)))
    q, _ = rank_ready(env, env.profile().engine)
    h = loop_health(len(loops), len(q.ranked), max(beats) if beats else 0.0, env.now(), env.profile().loop.absent)
    out = [f"last beat {ago(env.now(), h.last_beat)}"] if h.last_beat else []
    if last:
        detail = f": {last['detail']}" if last.get("detail") else ""
        out.append(f"last exit: {last.get('reason')}{detail} ({ago(env.now(), float(str(last.get('t') or 0)))})")
    if h.verdict == "absent":
        when = ago(env.now(), h.last_beat) if h.last_beat else "never"
        out.append(f"RED: {env.repo} has {h.ready} ready bead(s) and no loop alive (last beat {when}): "
                   f"start one with `tl loop --repo {env.repo}`")
    return out


def cmd_status(env: LoopEnv, files: LoopFiles, installs: Installs, a: Any) -> int:
    def t(x: float) -> str:
        return time.strftime("%m-%d %H:%M", time.localtime(x))
    loops = files.live()
    for st in loops:
        print(f"LOOP pid {st.pid} on {env.repo} since {t(st.started)}")
        if st.version:
            lag = env.behind(st.version)
            print(f"  running task-loop {st.version} from {st.code_dir or '?'}{f'; lags {lag} release(s)' if lag else ''}")
        if st.bead:
            print(f"  now: {st.bead} in {st.slot or 'its worktree'} since {t(st.since or 0)}; log {st.run_log}")
        mode = files.stop_for(st.pid)
        if mode:
            print(f"  stop requested: {mode}")
        if st.log:
            print(f"  log {st.log}")
    if not loops:
        print(f"no loop running on {env.repo}")
    for line in [*health_lines(env, files, loops), *env.ask_lines()]:
        print(line)
    for v, why in sorted(installs.refused().items()):  # a refused install still in the cache: red until a fixed release replaces it
        print(f"RED: task-loop {v} refused: {why[:160]}")
    rows = files.log_rows(a.last)
    if rows:
        print(table(["when", "bead", "slot", "outcome", "min", "rounds", "tests", "ask", "trace / why"]))
    for r in rows:
        print(table([str(r.get("ts") or "").replace("T", " ")[:16], str(r.get("bead")), str(r.get("slot") or "-"), str(r.get("outcome")),
                     str(r.get("minutes")), dash(r.get("rounds")), dash(r.get("tests_added")), "yes" if r.get("asked") else "no",
                     str(r.get("trace") or str(r.get("why") or "")[:60])]))
    return 0


def dash(v: object) -> str:
    return "-" if v is None else str(v)


def table(cols: list[str]) -> str:
    return f"{cols[0]:<16}  {cols[1]:<14} {cols[2]:<4} {cols[3]:<7} {cols[4]:>5} {cols[5]:>6} {cols[6]:>5} {cols[7]:<3}  {cols[8]}"


def cmd_loop(env: LoopEnv, files: LoopFiles, installs: Installs, a: Any) -> int:
    args = LoopArgs(max_beads=a.max_beads, until=a.until or "", wait_slot_min=a.wait_slot_min, wait_drained=a.wait_drained,
                    pin=a.pin, argv=list(a.argv))
    loop = Loop(env, files, installs, args, env.take_handover())
    main = threading.current_thread() is threading.main_thread()
    old = {sig: signal.signal(sig, lambda *_: loop.sigterm.set()) for sig in (signal.SIGTERM, signal.SIGINT)} if main else {}
    try:
        return loop.main()
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)
