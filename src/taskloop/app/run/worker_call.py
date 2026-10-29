"""WorkerCall: one AI step through delegate (contract 3). Delegate picks lane and model, limits apply, it records the run.

`run` builds the request (`RunRequest`, the only argv builder is its `to_argv`), makes the call, and for a stopped call asks
`lanes.policy.decide` what to do and lets `LaneActs` do it; a done call's answer is validated against the node's schema, a broken
one is asked for again (the `invalid_output` row of the RetryPlan). The call is on disk while it is in flight (CallState) so a killed
run, a sleeping laptop or a dropped network goes on in the same thread. The worker's life is delegate's: the engine reads the live
file's first line (`WorkerStarted`) and the answer's `worker`, and stops a call only through the process seam (stream-proc)."""

import hashlib
import json
import time
from dataclasses import dataclass, replace
from typing import Any

from taskloop.adapters import delegate as dg
from taskloop.adapters import delegate_wire
from taskloop.adapters import procs as sproc
from taskloop.app.run import done_memo, strays
from taskloop.app.run.calls import timing
from taskloop.app.run.lane_acts import LaneActs
from taskloop.contracts import answers
from taskloop.contracts import log as rec
from taskloop.contracts.delegate import REASON_OVERRUN, DelegateResult, RunRequest, StopFacts
from taskloop.contracts.schema import unstrict
from taskloop.domain.lanes import policy as lp
from taskloop.domain.lanes.denials import command_of, secret_false_positive
from taskloop.domain.lanes.notes import FRESH_WRITER_TEXT, RESUME_AFTER_STOP
from taskloop.domain.lanes.retry import PLAN
from taskloop.domain.lanes.roles import READ_ONLY_NODES, ROLES
from taskloop.stores import call_state as callstate

READ_TOOLS = ("Bash", "shell", "bash")


def stage_checks(plan: Any) -> list[str]:
    """Every check of the plan's stages (the plan is None before the first plan is accepted)."""
    return [c for st in (plan or {}).get("stages") or [] for c in st.get("checks") or []]


@dataclass
class Ops:
    """What the host (the engine) lends: its schemas, its text rules, and the Blocked/Kind of its close step."""

    summarize: Any
    read_only_command: Any
    blocked: Any  # (why, kind name, stop=None) -> the exception to raise
    stop_why: Any
    stop_say: Any
    after: Any  # (call, result): the node's detail lines and anomalies


class Call:
    """One AI step in flight: its prompts, thread and counters, which change between its delegate calls."""

    def __init__(
        self,
        node: str,
        role: str,
        schema: dict[str, Any],
        cwd: Any,
        full: str,
        text: str,
        writer: str | None,
        resume: str | None,
        key: tuple[Any, ...],
        resume_key: bool,
        writer_family: str | None,
        step: str | None,
        title: str,
    ) -> None:
        self.node, self.role, self.schema, self.cwd, self.full, self.text = node, role, schema, cwd, full, text
        self.writer, self.resume, self.key, self.resume_key, self.writer_family = writer, resume or None, key, resume_key, writer_family
        self.step, self.title, self.visual = step, title, False
        self.tries = 1  # calls that came back with no valid answer, from 1: two at most (RetryPlan invalid_output)
        self.counts: dict[str, float] = {
            "attempt": 0,
            "polls": 0,
            "crashes": 0,
            "waited_lane_s": 0.0,
            "waited_net_s": 0.0,
        }  # Ctx's counters
        self.denied_retried = False
        self.secret_fp = False  # the last denial was a `secrets` stop on a heredoc body that merely names .env
        self.was_resumed = bool(resume)
        self.out_on = ""  # the lane that went out under this step (the writer's fallback lane)
        self.up_now: bool | None = None  # the network probe at the last network stop
        self.finished: dg.Answer | None = None  # an answer the last run left on disk
        self.state: Any = None  # CallState
        self.sha = ""
        self.limit_s: float | None = None  # the --timeout the last call was given


class WorkerCall:
    def __init__(self, host: Any, ops: Ops) -> None:
        self.e, self.ops = host, ops
        self.acts = LaneActs(host, self)

    # -- the step
    def run(
        self,
        node: str,
        title: str,
        prompt: str,
        resume_key: Any = None,
        writer_family: str | None = None,
        step: str | None = None,
        resume_ref: str | None = None,
        visual: bool = False,
        delta: str | None = None,
        cwd: Any = None,
        at: tuple[int, ...] = (0, 0, 0),
        **meta: Any,
    ) -> tuple[Any, str]:
        """-> (the answer's data, its family)."""
        e = self.e
        e.halt_point()
        e.waits.budget_check()
        e.stats["nodes"] += 1
        c = self.start_call(node, title, prompt, resume_key, writer_family, step, resume_ref, visual, delta, cwd, at)
        e.steps.begin(step or node, f"{node}: {title}", node=node, backend="delegate", role=c.role, resume=bool(c.resume), **meta)
        while True:
            ans = c.finished or self.call_once(c)
            c.finished = None
            res = ans.res
            stop = lp.stop_of(res)
            c.secret_fp = secret_false_positive(res.denied)
            if stop is not None:
                if (
                    res.denied
                    and stop.scope == "bead"
                    and not any(d.kind == "secret" for d in res.denied)
                    and self.refused(c, res, res.denied)
                ):
                    continue
                self.acts.note_net(c, stop)
                self.acts.act(c, res, stop, lp.decide(stop, self.acts.ctx_of(c)))
                continue
            if self.acts.same_family(c, res):
                self.acts.refuse_same_family(c, res)
            errs = self.take_answer(c, res)
            if res.denied and self.refused(c, res, res.denied, errs):
                continue
            if not errs:
                break
            e.log.note(f"{node} output invalid (try {c.tries}): {'; '.join(errs[:4])}")
            if not PLAN.left("invalid_output", c.tries - 1):
                raise self.ops.blocked("failed: {} node produced no valid output ({})".format(node, "; ".join(errs[:3])), "FAULT_INFRA")
            e.steps.move(step or node, "invalid_output", "; ".join(errs[:2]))
            c.tries += 1
            self.again(c)  # a refused or broken resume is not worth a second attempt: a new thread
        self.end_call(c, ans)
        return res.data, res.family or "delegate"

    def start_call(
        self,
        node: str,
        title: str,
        prompt: str,
        resume_key: Any,
        writer_family: str | None,
        step: str | None,
        resume_ref: str | None,
        visual: bool,
        delta: str | None,
        cwd: Any,
        at: tuple[int, ...],
    ) -> Call:
        e = self.e
        writer = writer_family if node in READ_ONLY_NODES else None
        resume = resume_ref or (e.writer.get("delegate") if resume_key else None)
        if resume and resume_key and e.writer_fallback:  # tl-bxk.10.5: a fallback writer would keep the bead off Codex for good
            lane = dg.lane_status(e.delegation.route() or "").get(e.fallback_lane) if e.fallback_lane else None
            if e.fallback_lane and not isinstance(lane, dict):  # that lane is not configured here: no fallback
                e.writer_fallback, e.fallback_lane = False, ""
            elif lane is None or lane.get("out") is False:  # back again, or no lane known to wait for
                e.steps.move(
                    step or node,
                    "fallback_retake",
                    "{}: delegate routes afresh instead of resuming the fallback writer ({})".format(
                        f"{e.fallback_lane} is usable again" if e.fallback_lane else "its first-choice lane is not known",
                        e.writer_family or "?",
                    ),
                )
                resume, prompt = None, prompt + FRESH_WRITER_TEXT
        e.publish_plan()  # an unsandboxed worker can write here: every step reads the engine's plan
        text = delta if (delta and resume and resume_key) else prompt
        c = Call(
            node,
            ROLES[node],
            answers.sent_schema(node, visual),
            cwd or e.wt,
            prompt,
            text,
            writer,
            resume,
            (step or node, *tuple(at)),
            bool(resume_key),
            writer_family,
            step,
            title,
        )
        c.visual = visual
        self.attach(c)
        return c

    # -- the checkpoint of a call in flight
    def attach(self, c: Call) -> None:
        """What the last run left of this call on disk (CallState): a finished answer is used as it stands (output is never discarded),
        a call that had a thread goes on in that thread with a short note; else the call is made as usual."""
        e = self.e
        c.sha = hashlib.sha1(c.full.encode("utf-8")).hexdigest()[:16]
        done = done_memo.recall(self.e.run_dir, c.key, c.sha)
        if done is not None:  # this run (before a network pause or a move) already had this answer for this very prompt
            e.log.note(f"{c.node}: the answer of this run's earlier pass is on disk: used, not asked again")
            c.finished = dg.Answer(delegate_wire.result_of(done), done)
            return
        st = callstate.load_for(e.call_dir(), e.bead, c.key)
        what = callstate.reattach(st) if st is not None and st.prompt_sha == c.sha else None
        if what and what[0] == "answer":
            e.log.note(f"{c.node}: the answer of the last run is on disk: used, not asked again")
            c.finished = dg.Answer(delegate_wire.result_of(what[1]), what[1])
            c.state = st
        elif what:
            e.log.note(f"{c.node}: the last run left thread {what[1]}: going on in it")
            c.resume, c.text = what[1], what[2]
            c.was_resumed = True

    # -- one call
    def limits(self, c: Call) -> tuple[int, int]:
        """(delegate's --timeout, its --idle) in seconds. A write has one wall cap and delegate's silence limit (its watchdog stops a hung
        worker: a typed stop in the answer); a reviewer call has a wall-time budget; the others have the node limit."""
        cfg = self.e.cfg
        if c.node == "write":
            return int(float(cfg.write_cap_min) * 60), int(float(cfg.write_idle_min) * 60)
        if c.node in READ_ONLY_NODES:
            return int(float(cfg.review_budget_min) * 60), 0
        return int(float(cfg.node_timeout_min) * 60), 0

    def call_once(self, c: Call) -> dg.Answer:
        """One `route.py run`: through the process seam, then the records a call leaves."""
        e = self.e
        timeout_s, idle_s = self.limits(c)
        c.limit_s = float(timeout_s)
        e.delegation.route()
        live = e.live(c.step or c.node)
        runner = e.router.runner(e.err_path, None, live, e.lock_worker)
        runner.outer = e.halt  # a stop of the run ends the call
        req = RunRequest(
            role=c.role,
            brief_path="",
            cwd=str(c.cwd),
            schema_path="",
            parent=e.session,
            task=e.bead,
            title=f"{e.bead} · {c.node}: {c.title}",
            resume=c.resume or "",
            authored_by=c.writer or "",
            timeout_s=timeout_s,
            idle_s=idle_s,
            live_file=live,
            engine_only=e.checker.split().engine_recipes(stage_checks(e.plan_data)) if c.node == "write" else [],
        )
        cid = e.calls.start(c.step or c.node, c.node, c.role, bool(c.resume), e.live_n)
        c.state = callstate.begin(
            e.call_dir(), e.log_path.stem, e.bead, c.key, c.role, resume_of=c.resume or "", prompt_sha=c.sha, now=e.clock.now()
        )
        t0, trees = time.time(), strays.worktrees(e)  # the worktrees the repo holds before the worker runs
        try:
            ans = dg.call(e.resolved, req, c.text, c.schema, runner, env=sproc.current_env(e.bead_env))
        except BaseException as exc:  # an interruption stopped the delegate inside the process seam: record that stop here
            if runner.obs.get("kill_t") or runner.stop.get("alive"):
                self.log_kill(c, runner, exc)
            e.log.emit(rec.CallEnd(id=cid, status="stopped", reason="interrupted"))
            raise
        ans = self.overrun(c, ans, runner, time.time() - t0)
        res = ans.res
        e.cost += res.cost
        stopped = runner.stop.get("why") or ""
        survivors = self.survivors(runner, res)
        e.calls.end(cid, c.node, c.role, c.tries, res, stopped, bool(c.resume), len(c.text), runner.worker, runner.live_start())
        if stopped or survivors:  # the actual stop path, including a worker that outlived every signal
            self.log_kill(c, runner, survivors=survivors)
        e.lock_workers(survivors, runner.worker)
        if survivors:  # a retry would write into the tree the old worker still writes in
            raise self.ops.blocked(
                "failed: the {} worker (pid {}) is still alive after the stop ({}), SIGTERM and SIGKILL; "
                "not retrying into this worktree. Kill it, then rerun.".format(
                    c.node, ", ".join(str(p) for p in survivors), stopped or "worker_survived"
                ),
                "FAULT_SLOT",
            )
        e.halt_point()  # the call was ended by a stop: no retry, no verdict from it
        strays.check(e, trees, self.ops.blocked)  # tl-7y6.24: a worker that went outside its slot fails the bead; nothing is repaired
        self.note_result(c, ans, runner)
        return ans

    def survivors(self, runner: Any, res: DelegateResult) -> list[int]:
        """Pids that outlived the stop of this call: stream-proc's proof of the route.py tree, and the worker pids delegate names as
        survivors in its own answer (`worker.end` worker_survived)."""
        pids = [int(p) for p in runner.stop.get("alive") or []]
        pids += [s.pid for s in (res.worker.survivors if res.worker else []) if s.pid not in pids]
        return pids

    def overrun(self, c: Call, ans: dg.Answer, runner: Any, elapsed: float) -> dg.Answer:
        """A reviewer call that used its budget (delegate stopped its worker at --timeout, or the engine's backstop did): an Overrun record,
        and the call becomes a stop of its lane, which the policy routes past (the next reviewer rung)."""
        res = ans.res
        if c.node not in READ_ONLY_NODES or c.limit_s is None:
            return ans
        wall = runner.stop.get("kind") == "wall"
        if not (wall or (res.stop is not None and res.stop.reason == delegate_wire.REASON_TIMEOUT)):
            return ans
        live = runner.live_start()
        lane = res.lane or (live.lane if live else "")
        self.e.log.emit(rec.Overrun(stage=c.step or c.node, budget_s=c.limit_s, elapsed_s=round(max(elapsed, res.secs), 1), lane=lane))
        stop = StopFacts(
            reason=REASON_OVERRUN, scope="lane", permanence="transient", retry=delegate_wire.Retry(kind="none"), ref=res.ref or ""
        )
        return dg.Answer(
            replace(res, stop=stop, lane=lane or None, say=f"the {c.node} call used its {int(c.limit_s // 60)} min budget"), ans.raw
        )

    def note_result(self, c: Call, ans: dg.Answer, runner: Any) -> None:
        """The records a returned call leaves: the vendor error of a stop, the CallState."""
        e, res = self.e, ans.res
        if res.stop is not None:
            s = res.stop
            e.log.emit(
                rec.VendorError(
                    node=e.steps.id,
                    reason=s.reason or res.say or "stopped",
                    lane=res.lane or "",
                    model=res.model or "",
                    error=(res.first_error or res.say or "")[:300],
                    error_observed=bool(res.first_error),
                    **timing(runner.obs),
                )
            )
            if res.ref and s.resumable:  # the thread this stop can go on in; any other stop forgets it (a lane that is out cannot resume)
                c.state.note_ref(res.ref, e.clock.now())
            else:
                c.state.ref = ""
                c.state.save()
        else:
            c.state.returned(ans.raw, e.run_dir / f"{c.node}-{e.stats['nodes']}.raw.json", e.clock.now())

    def log_kill(self, c: Call, runner: Any, exc: BaseException | None = None, survivors: list[int] | None = None) -> None:
        o, st = runner.obs, runner.stop
        started = o.get("started_t")
        why = st.get("why") or o.get("why") or ("interrupted" if exc is not None else "worker survived the stop")
        self.e.log.emit(
            rec.Kill(
                what=c.node,
                why=why,
                secs=round(time.time() - started) if started else 0,
                alive=list(survivors if survivors is not None else [int(p) for p in st.get("alive") or []]),
                observed_t=o.get("kill_t") or o.get("ended_t"),
                **timing(o),
            )
        )

    # -- the answer
    def take_answer(self, c: Call, res: DelegateResult) -> list[str]:
        """A done answer: the writer's thread and fallback bookkeeping, then the data against its schema. -> the errors ([] valid)."""
        e = self.e
        if res.git_violation:
            e.warn("{} changed git: {}".format(c.node, "; ".join(res.git_violation)))
        if c.resume_key and res.ref:
            if res.fallback is not None:  # delegate says it on every answer that picked a lane, a resumed one too
                e.writer_fallback = res.fallback
                e.fallback_lane = (res.first_lane or c.out_on or e.fallback_lane) if res.fallback else ""
            e.writer["delegate"] = c.resume = res.ref
            e.writer["ctx"] = (e.sessions[-1] if e.sessions else {}).get("context_k")  # k tokens, None = unknown
            e.writer["seen"] = e.hand.seen_now()  # the brief and plan this session now holds
        data = unstrict(res.data, answers.schema_for(c.node, c.visual)) if res.data is not None else None
        return answers.check(c.node, c.visual, data) if data is not None else [f"no structured output: {(res.say or res.text)[:300]}"]

    def refused(self, c: Call, res: DelegateResult, denied: list[Any], errs: Any = True) -> bool:
        """The guard refused commands during this step. -> True when the step goes again on a fresh thread (it refused only reads)."""
        e = self.e
        said = "; ".join(f"`{command_of(d)}`" for d in denied)
        if (
            errs
            and PLAN.left("denied_read", int(c.denied_retried))
            and all(d.tool in READ_TOOLS and self.ops.read_only_command(command_of(d)) for d in denied)
        ):
            # tl-bxk.10.21: a guard refused only commands that read (lifesim-6dq0: a head+rg chain, 12 s, no answer; the next run found
            # the work done). One retry on a fresh thread that is told what was refused; a second denial blocks
            c.denied_retried = True
            note = (
                "\nAn earlier attempt at this step (thread {}) was refused a read-only command: {}. Do not run it again. "
                "Read with one plain command at a time, such as `rg -n PATTERN PATH`, `cat FILE` or `git diff`, "
                "with no pipes, chains or substitutions, then give your answer.".format(res.ref or "unknown", said)
            )
            e.warn(f"{c.node}: read-only command refused ({said}); retrying once on a fresh thread")
            e.steps.move(c.step or c.node, "denied_retry", f"refused read-only: {said[:200]}")
            self.again(c, note=note)
            return True
        if errs:  # asking again meets the same refusal
            raise self.ops.blocked(
                "needs a human: the {} step was denied {} and gave no answer; run it or allow it, then rerun. ({})".format(
                    c.node, said, (res.text or res.say or "")[:200]
                ),
                "FAULT_DENIED",
            )
        if c.node == "write":  # once is a warning; twice in a bead is a pattern the owner must see
            e.denials.append(said)
            if len(e.denials) >= 2:
                raise self.ops.blocked(
                    f"needs a human: the writer was refused commands {len(e.denials)} times in this task (a reworded "
                    f"command may be a way around a refusal): {' | '.join(e.denials)}. Run or allow them, then rerun.",
                    "FAULT_DENIED",
                )
        e.warn(f"{c.node} was denied {said} and found another way")
        return False

    def again(self, c: Call, resume: str = "", note: str = "", stop: lp.Stop | None = None) -> None:
        """The next call of this step: on thread `resume` with a short note of why, else on a new thread with the whole prompt."""
        if resume:
            c.resume = resume
            c.text = callstate.NETWORK_RESUME_DELTA if stop is not None and stop.reason == "network" else RESUME_AFTER_STOP
        else:
            c.text = c.full + (FRESH_WRITER_TEXT if c.resume else "") + note
            c.resume = None

    def charge(self, c: Call, name: str, secs: float = 0.0) -> None:
        if name == "denied_retried":
            c.denied_retried = True
        elif name in ("waited_lane_s", "waited_net_s"):
            c.counts[name] += secs
        elif name:
            c.counts[name] += 1

    def end_call(self, c: Call, ans: dg.Answer) -> None:
        e, res = self.e, ans.res
        if c.state is not None:
            c.state.consumed()
            done_memo.keep(e.run_dir, c.key, c.sha, c.state.answer_file if c.state else "")
        if c.node == "plan" and res.ref:
            e.planner_ref = res.ref
        e.last_flag = res.flag  # same_family | degraded | ...: delegate could not give the usual lane
        if c.node in READ_ONLY_NODES and c.writer_family and res.family == c.writer_family and not e.last_flag:
            e.last_flag = "same_family"  # routed past a dead lane to the writer's own family: say so
        if e.last_flag == "same_family" or res.warning.strip():
            # the owner's word: when only one family is up, it reviews its own work; say so (delegate's warning when it gives one),
            # in the log, the trace and the bead, and never pause for it
            note = "the {} step ran on the writer's own model family{}".format(
                c.node, (": " + res.warning.strip()[:300]) if res.warning.strip() else " (no other lane was free)"
            )
            if note not in e.lane_notes:
                e.lane_notes.append(note)
                e.warn(note)
                e.comment("Lane (engine): " + note)
        model = f"{res.model} {res.effort} on {res.lane}"
        (e.run_dir / f"{c.node}-{e.stats['nodes']}.json").write_text(json.dumps(res.data, indent=1))
        shown = self.ops.summarize(c.node, res.data)
        via = f"{res.family or 'delegate'}{(':' + model) if model else ''}"
        e.log.note(f"{c.node} → {shown}  [{via}, {int(res.secs)}s, ${res.cost:.2f}, total ${e.cost:.2f}]")
        self.ops.after(c, res)
