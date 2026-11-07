"""WorkerCall: one AI step through delegate (contract 4). Delegate picks lane and model, limits apply, it records the run.

`run` builds the request (`RunRequest`; the engine builds no argv), makes the call, and for a stopped call asks
`lanes.policy.decide` what to do and lets `LaneActs` do it; a done call's answer is validated against the node's schema, a broken
one is asked for again (the `invalid_output` row of the RetryPlan). The call is on disk while it is in flight (CallState) so a killed
run, a sleeping laptop or a dropped network goes on in the same thread. The worker's life is delegate's: the engine reads the live
file's first line (`WorkerStarted`) and the answer's `worker`, and stops a call only through the process seam (stream-proc)."""

import json
import time
from dataclasses import dataclass
from typing import Any

from tlkernel import answers, childenv
from tlkernel import log as rec
from tlkernel.asked import Asked, Updates
from tlkernel.delegate import REASON_OVERRUN, DelegateResult, RunRequest, StopFacts
from tlkernel.delegateport import Answer

from taskloop.adapters import delegate_wire
from taskloop.app.checks.step_env import step_env
from taskloop.app.workers import asked, strays, worker_identity, worker_recovery, worker_request
from taskloop.app.workers import call_state as callstate
from taskloop.app.workers.call import Call
from taskloop.app.workers.calls import timing
from taskloop.app.workers.lane_acts import LaneActs
from taskloop.domain.lanes import policy as lp
from taskloop.domain.lanes.denials import command_of, secret_false_positive
from taskloop.domain.lanes.retry import PLAN
from taskloop.domain.lanes.roles import READ_ONLY_NODES, ROLES

READ_TOOLS = ("Bash", "shell", "bash")


@dataclass
class Ops:
    """What the host (the engine) lends: its schemas, its text rules, and the Blocked/Kind of its close step."""

    summarize: Any
    read_only_command: Any
    blocked: Any  # (why, kind name, stop=None) -> the exception to raise
    stop_why: Any
    stop_say: Any
    after: Any  # (call, result): the node's detail lines and anomalies


class WorkerCall:
    def __init__(self, host: Any, ops: Ops) -> None:
        self.e, self.ops = host, ops
        self.acts = LaneActs(host, self)
        self.active: Call | None = None

    # -- the step
    def run(
        self,
        node: str,
        title: str,
        prompt: str,
        resume_key: Any = None,
        writer_family: str | None = None,
        step: str | None = None,
        thread: str = "",
        visual: bool = False,
        delta: str | None = None,
        boundary: bool = False,
        cwd: Any = None,
        at: tuple[int, ...] = (0, 0, 0),
        **meta: Any,
    ) -> Asked:
        """-> the answer's data and family, and what it says about the run's threads (the caller applies them)."""
        e = self.e
        e.halt_point()
        e.waits.budget_check()
        e.stats["nodes"] += 1
        c = self.start_call(node, title, prompt, resume_key, writer_family, step, thread, visual, delta, cwd, at, boundary)
        e.steps.begin(step or node, f"{node}: {title}", node=node, backend="delegate", role=c.role, resume=bool(c.delta), **meta)
        while True:
            ans = c.finished or self.call_once(c)
            c.finished = None
            res = ans.res
            stop = None if lp.net_data(res) and not answers.sent_errors(c.node, c.visual, res.data, res.say) else lp.stop_of(res)
            c.secret_fp = secret_false_positive(res.denied)
            if stop is not None:
                if (
                    res.denied
                    and stop.scope == "bead"
                    and not any(d.kind == "secret" for d in res.denied)
                    and self.refused(c, res, res.denied)
                ):
                    continue
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
        done = self.end_call(c, ans)
        return Asked(res.data if res.data is not None else {}, res.family or "delegate", done)

    def start_call(
        self,
        node: str,
        title: str,
        prompt: str,
        resume_key: Any,
        writer_family: str | None,
        step: str | None,
        thread: str,
        visual: bool,
        delta: str | None,
        cwd: Any,
        at: tuple[int, ...],
        boundary: bool = False,
    ) -> Call:
        e = self.e
        has_thread = bool(resume_key and delta is not None)
        e.publish_plan()  # an unsandboxed worker can write here: every step reads the engine's plan
        delta = delta if (bool(e.planner_ref) if node == "plan" else has_thread or thread) else None
        key = (step or node, *tuple(at))
        c = Call(
            node,
            ROLES[node],
            answers.sent_schema(node, visual),
            cwd or e.wt,
            prompt,
            prompt,
            delta,
            key,
            "writer" if resume_key else "planner" if node == "plan" else "/".join(map(str, key)),
            step,
            title,
        )
        c.boundary = boundary
        c.visual = visual
        self.attach(c)
        if node == "plan":
            c.delta = delta
        return c

    # -- the checkpoint of a call in flight
    def attach(self, c: Call) -> None:
        """Recover only work proved compatible with the current effective request and tree."""
        e = self.e
        self.active = c
        c.prepared = self.prepare(c)
        c.sha = c.prepared.execution_id
        journal = worker_recovery.CallJournal(e.run_dir, e.call_dir(), e.bead, c.key)
        decision = worker_recovery.recover(c.prepared, journal)
        if isinstance(decision, worker_recovery.Returned):
            e.log.note(f"{c.node}: compatible completed execution on disk: using answer")
            c.finished = Answer(delegate_wire.result_of(decision.raw), decision.raw)
            c.state = decision.state
        elif isinstance(decision, worker_recovery.Resuming):
            e.log.note(f"{c.node}: compatible interrupted thread {decision.ref}: resuming")
            c.delta = decision.text
        elif decision.reason:
            e.log.note(f"{c.node}: {decision.reason}")

    def prepare(self, c: Call) -> worker_identity.PreparedCall:
        req = self.request(c, "", *self.limits(c))
        return worker_recovery.prepare_call(
            worker_identity.NodeInput(c.node, c.full, c.schema, req),
            worker_identity.context(self.e.git, str(self.e.wt), str(c.cwd)),
        )

    def saved(self) -> None:
        """Rebind an interrupted thread to the close's saved WIP tree and commit."""
        c = self.active
        if c is not None and c.prepared is not None and c.state is not None and c.state.phase == "calling" and c.state.ref:
            current = worker_identity.context(self.e.git, str(self.e.wt), str(c.cwd))
            c.prepared = worker_recovery.saved(c.prepared, c.state, current)
            c.sha = c.prepared.execution_id

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

    def request(self, c: Call, live: str, timeout_s: int, idle_s: int) -> RunRequest:
        """Only a pinned write may ask delegate to treat the engine-only guard as advisory."""
        return worker_request.request(self.e, c, live, timeout_s, idle_s)

    def call_once(self, c: Call) -> Answer:
        """One delegate call: through the process seam, then the records a call leaves."""
        e = self.e
        worker_request.refuse_over_cap(e, c.node, c.role, c.text)
        e.delegation.route()
        live = e.live(c.step or c.node)
        c.prepared = self.prepare(c)
        c.sha = c.prepared.execution_id
        req = c.prepared.request.replace(live_file=live, tools=[worker_request.artifact_tool(e, c)])  # per call: not in the call's identity
        c.limit_s = float(req.timeout_s)
        brief = worker_request.brief(e, c, req)
        delta = c.delta
        if delta is not None:
            delta += brief[len(c.text):]
            worker_request.refuse_over_cap(e, c.node, c.role, delta)
        runner = e.router.runner(e.err_path, None, live)
        runner.outer = e.halt  # a stop of the run ends the call
        cid = e.calls.start(c.step or c.node, c.node, c.role, bool(c.delta), e.live_n)
        c.state = callstate.begin(
            e.call_dir(), e.run_id, e.bead, c.key, c.role, execution_id=c.sha, now=e.clock.now()
        )
        t0, trees = time.time(), strays.worktrees(e)  # the worktrees the repo holds before the worker runs
        try:
            wenv = {**e.bead_env, **step_env(e, c.step or c.node)}
            ans = e.router.call(e.resolved, req, brief, c.schema, runner, env=childenv.delegate_call_env(e.env, wenv), delta=delta)
        except BaseException as exc:  # an interruption stopped the delegate inside the process seam: record that stop here
            if runner.obs.get("kill_t") or runner.survivors():
                self.log_kill(c, runner, exc)
            e.log.emit(rec.CallEnd(id=cid, status="stopped", reason="interrupted"))
            raise
        ans = self.overrun(c, ans, runner, time.time() - t0)
        res = ans.res
        e.cost += res.cost
        stopped = runner.stop.get("why") or ""
        survivors = runner.survivors(res)
        sent = len(delta if delta is not None else brief)
        e.calls.end(cid, c.node, c.role, c.tries, res, stopped, bool(c.delta), sent, runner.worker, runner.live_start())
        if stopped or survivors:  # the actual stop path, including a worker that outlived every signal
            self.log_kill(c, runner, survivors=survivors)
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

    def overrun(self, c: Call, ans: Answer, runner: Any, elapsed: float) -> Answer:
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
        said = f"the {c.node} call used its {int(c.limit_s // 60)} min budget"
        return Answer(res.replace(stop=stop, lane=lane or None, say=said), ans.raw, ans.argv, ans.trace)

    def note_result(self, c: Call, ans: Answer, runner: Any) -> None:
        """The records a returned call leaves: the vendor error of a stop, the CallState."""
        e, res = self.e, ans.res
        assert c.state is not None
        if res.stop is not None:
            s = res.stop
            worker_request.note_write_stop(e, c, ans)
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
        if res.stop is None or lp.net_data(res):  # a network stop with data: finished output is never thrown away
            assert c.prepared is not None
            worker_recovery.record_returned(
                c.prepared, c.state, e.git, ans.raw, e.run_dir / f"{c.node}-{e.stats['nodes']}.raw.json", e.clock.now()
            )

    def log_kill(self, c: Call, runner: Any, exc: BaseException | None = None, survivors: list[int] | None = None) -> None:
        o, st = runner.obs, runner.stop
        started = o.get("started_t")
        why = st.get("why") or o.get("why") or ("interrupted" if exc is not None else "worker survived the stop")
        self.e.log.emit(
            rec.Kill(
                what=c.node,
                why=why,
                secs=round(time.time() - started) if started else 0,
                alive=list(survivors if survivors is not None else runner.survivors()),
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
        seen = e.hand.seen_now() if c.thread == "writer" and res.ref else []
        c.updates = asked.then(c.updates, asked.thread_updates(c, res, seen))
        return answers.sent_errors(c.node, c.visual, res.data, res.say or res.text)

    def refused(self, c: Call, res: DelegateResult, denied: list[Any], errs: Any = True) -> bool:
        """The guard refused commands during this step. -> True when the step goes again on a fresh thread (it refused only reads)."""
        e = self.e
        said = "; ".join(f"`{command_of(d)}`" for d in denied)
        if (
            errs
            and PLAN.left("denied_read", int(c.denied_retried))
            and all(d.tool in READ_TOOLS and self.ops.read_only_command(command_of(d)) for d in denied)
        ):
            # tl-bxk.10.21: a guard refused only commands that read (a consumer run: a head+rg chain, 12 s, no answer; the next run found
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

    def again(self, c: Call, note: str = "") -> None:
        """The next call starts a new thread with the whole prompt."""
        c.delta = None
        c.text = c.full + note

    def charge(self, c: Call, name: str) -> None:
        if name == "denied_retried":
            c.denied_retried = True
        elif name:
            c.counts[name] += 1

    def end_call(self, c: Call, ans: Answer) -> Updates:
        """The call's updates to the run's threads, kept with the memo; the caller applies them to the engine."""
        e, res = self.e, ans.res
        done = asked.done_updates(c, res, c.updates)
        if c.state is not None and c.prepared is not None:
            # the memo first, with the thread's fields in one transaction: a crash between this and consumed re-recovers, never loses
            asked.settle(e, c, done, c.state.answer_file, c.prepared.snapshot)
            c.state.consumed()
        if done.flag == "same_family" or res.warning.strip():
            # the owner's word: when only one family is up, it reviews its own work; say so (delegate's warning when it gives one),
            # in the log, the trace and the bead, and never pause for it
            note = "the {} step ran on the writer's own model family{}".format(
                c.node, (": " + res.warning.strip()[:300]) if res.warning.strip() else " (no other lane was free)"
            )
            if note not in e.write.lane_notes:
                e.write.lane_notes.append(note)
                e.warn(note)
                e.comment("Lane (engine): " + note)
        model = f"{res.model} {res.effort} on {res.lane}"
        (e.run_dir / f"{c.node}-{e.stats['nodes']}.json").write_text(json.dumps(res.data, indent=1))
        shown = self.ops.summarize(c.node, res.data)
        via = f"{res.family or 'delegate'}{(':' + model) if model else ''}"
        e.log.note(f"{c.node} → {shown}  [{via}, {int(res.secs)}s, ${res.cost:.2f}, total ${e.cost:.2f}]")
        self.ops.after(c, res)
        return done
