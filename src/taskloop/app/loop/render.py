"""Loop command results and their text, independent of the CLI."""

import json
import time
from collections.abc import Sequence

from tlkernel.ago import ago
from tlkernel.loop import LoopState
from tlkernel.reconcile import LoopFact, loop_absent

from taskloop.app.loop.env import LoopEnv
from taskloop.app.loop.files import LoopFiles
from taskloop.app.loop.queue import Queue, rank_ready
from taskloop.app.loop.versions import Installs


def cmd_next(env: LoopEnv, only: Sequence[str], as_json: bool) -> tuple[list[str], int]:
    out: list[str] = []
    env.fetch()
    q, rule = rank_ready(env, env.profile().engine, say=out.append, only=only)
    lines, code = next_lines(q, rule.chosen, rule.only, as_json)
    return out + lines, code


def next_lines(q: Queue, chosen: Sequence[str], only: bool, as_json: bool) -> tuple[list[str], int]:
    """Render a ranked snapshot without reading state or printing."""
    out: list[str] = []
    ranked, skipped = q.ranked, q.skipped
    if as_json:
        out.append(
            json.dumps(
                {
                    "pick": ranked[0].bead.to_dict() if ranked else None,
                    "reason": ranked[0].reason if ranked else "",
                    "next": [{"id": r.bead.id, "priority": r.bead.priority, "reason": r.reason} for r in ranked[1:6]],
                    "skipped": [{"id": s.bead, "why": s.skip.why} for s in skipped],
                },
                ensure_ascii=False,
            )
        )
        return out, 0 if ranked else 1
    if not ranked:
        out.append("NONE: no ready bead in the queue")
    for n, r in enumerate(ranked[:6]):
        out.append(f"{'NEXT' if n == 0 else 'then'} {r.bead.id}  P{r.bead.priority}  {r.bead.title[:70]}  ({r.reason})")
    if chosen:
        out.append(f"{'ONLY' if only else 'QUEUE'}: {', '.join(chosen)}")
    for s in skipped:
        out.append(f"skip {s.bead}: {s.skip.why}")
    return out, 0 if ranked else 1


def cmd_stop(env: LoopEnv, files: LoopFiles, now: bool) -> tuple[list[str], int]:
    """Every loop running on the repo stops (a loop started later does not read this command)."""
    return stop_lines(env.repo, files.request_stop(now, env.actor()), now)


def stop_lines(repo: str, loops: list[LoopState], now: bool) -> tuple[list[str], int]:
    """Render the loops named by a stop request."""
    if not loops:
        return [f"no loop running on {repo}"], 1
    return [
        f"STOP {'NOW' if now else 'after the current bead'}: loop pid {st.pid}" + (f", running {st.bead}" if st.bead else "")
        for st in loops
    ], 0


def health_lines(env: LoopEnv, files: LoopFiles, loops: list[LoopState]) -> list[str]:
    """Under the loop list: how long since the last beat, the last exit reason, and one RED line for an absent loop."""
    beats = [st.t or st.started for st in loops]
    last = files.last_exit()
    if not beats:
        beats = [st.t or st.started for st in files.died()]
        beats.append(float(str(last.get("t") or 0)))
    diagnostics: list[str] = []
    q, _ = rank_ready(env, env.profile().engine, say=diagnostics.append)
    last_beat = max(beats) if beats else 0.0
    out = [f"last beat {ago(env.now(), last_beat)}"] if last_beat else []
    if last:
        detail = f": {last['detail']}" if last.get("detail") else ""
        out.append(f"last exit: {last.get('reason')}{detail} ({ago(env.now(), float(str(last.get('t') or 0)))})")
    facts = tuple(LoopFact(st.pid, st.started, st.t or st.started) for st in loops)
    if loop_absent(facts, len(q.ranked), last_beat, env.now(), env.profile().loop.absent):
        when = ago(env.now(), last_beat) if last_beat else "never"
        out.append(
            f"RED: {env.repo} has {len(q.ranked)} ready bead(s) and no loop alive (last beat {when}): "
            f"start one with `tl loop --repo {env.repo}`"
        )
    return diagnostics + out


def cmd_status(env: LoopEnv, files: LoopFiles, installs: Installs, last: int) -> tuple[list[str], int]:
    def t(x: float) -> str:
        return time.strftime("%m-%d %H:%M", time.localtime(x))

    out: list[str] = []
    loops = files.live()
    for st in loops:
        out.append(f"LOOP pid {st.pid} on {env.repo} since {t(st.started)}")
        if st.version:
            lag = env.behind(st.version)
            out.append(f"  running task-loop {st.version} from {st.code_dir or '?'}{f'; lags {lag} release(s)' if lag else ''}")
        if st.bead:
            out.append(f"  now: {st.bead} in {st.slot or 'its worktree'} since {t(st.since or 0)}; log {st.run_log}")
        mode = files.stop_for(st.pid, st.started)
        if mode:
            out.append(f"  stop requested: {mode}")
        if st.log:
            out.append(f"  log {st.log}")
    if not loops:
        out.append(f"no loop running on {env.repo}")
    for line in [*health_lines(env, files, loops), *env.ask_lines()]:
        out.append(line)
    for v, why in sorted(installs.refused().items()):  # a refused install still in the cache: red until a fixed release replaces it
        out.append(f"RED: task-loop {v} refused: {why[:160]}")
    page = files.log_rows(last)
    rows = [i.rec for i in page.items]
    out.extend(skipped_lines(page.skipped))
    if rows:
        out.append(table(["when", "bead", "slot", "outcome", "min", "rounds", "tests", "ask", "trace / why"]))
    for r in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r.t))
        out.append(
            table(
                [
                    when,
                    r.bead,
                    r.slot or "-",
                    r.outcome.value,
                    str(r.minutes),
                    str(r.rounds),
                    str(r.tests_added),
                    "yes" if r.asked else "no",
                    r.run_id or r.why[:60],
                ]
            )
        )
    return out, 0


def skipped_lines(n: int) -> list[str]:
    return [f"{n} log line(s) of an older version skipped"] if n else []


def table(cols: list[str]) -> str:
    return f"{cols[0]:<16}  {cols[1]:<14} {cols[2]:<4} {cols[3]:<7} {cols[4]:>5} {cols[5]:>6} {cols[6]:>5} {cols[7]:<3}  {cols[8]}"


def cutover_lines(live: list[tuple[str, str]], as_json: bool) -> tuple[list[str], int]:
    if as_json:
        lines = [json.dumps({"live": [{"kind": k, "what": w} for k, w in live]})]
    elif live:
        lines = ["\n".join(f"LIVE {w}" for _, w in live)]
    else:
        lines = ["CLEAR: no live loop or run"]
    return lines, 1 if live else 0
