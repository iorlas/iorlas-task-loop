"""Run: the single entry of `route.py run`. One call, end to end: decide the lane (decide.py), refuse without launching when the answer is
a stop, claim a lease (lease.py), launch the worker (launch.py) behind the canary, the network retry and the schema re-ask, record
history, and print one
JSON answer. Every outcome, including a crash, is an answer; exit 0 whenever it was printed."""

import argparse
import contextlib
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from delegate.adapters import git, procs
from delegate.app import answer, cockpit, codex_policy, decide, env, harnesses, launch, net, usage, watch
from delegate.app.launch import how_of
from delegate.app.lease import RunLease
from delegate.app.run_end import file_size, history_row, transcript_info, worker_ended
from delegate.app.supervisor import RunHooks
from delegate.contracts import history as hist
from delegate.contracts.json_types import Json, arr, as_num, as_opt_bool, as_opt_int, as_opt_obj, as_opt_str, as_str, obj
from delegate.contracts.state import RefRecord, StateDoc
from delegate.contracts.stores import StateUnreadable
from delegate.domain.cost import accounting
from delegate.domain.health import ledger as health_ledger
from delegate.domain.holds.book import HoldBook
from delegate.domain.lanes import profiles
from delegate.domain.lanes.lane import Lane
from delegate.domain.policy.worker import GIT_RULES, SECRET_RULE

CANARY_BRIEF = "Reply with exactly: OK"
CANARY_TIMEOUT_S = 30
IDENTITY = ("lane", "model", "effort", "family", "flag", "rung", "fallback", "fallback_reason", "first_lane")


class Run:
    def __init__(
        self,
        a: env.Args,
        cfg: dict[str, Json],
        unattended: bool = False,
        idle_s: float | None = None,
        brief: str | None = None,
        log: Callable[[str], None] | None = None,
    ):
        """`brief` given: the call reads no file and no stdin. `log` receives the lines the CLI prints on stderr (default: stderr)."""
        self.a, self.cfg, self.unattended, self.idle_s, self.given_brief = a, cfg, unattended, idle_s, brief
        self.log = log or (lambda line: print(line, file=sys.stderr, flush=True))
        self.out: dict[str, Json] = {}  # the answer, set by emit
        self.on_started: Callable[[str, procs.Worker], None] | None = None  # (run_id, worker): the worker exists
        self.extra: dict[str, Json] = {}  # fields every answer of this call carries: warnings, notice, needs_input
        self.settler = launch.settler()
        self.git_before: dict[str, str] | None = None
        self.keep_ref: Callable[[str], None] = lambda ref: None  # replaced by _hooks, before any launch

    def _family(self, d: dict[str, Json]) -> Json:
        return obj(obj(self.cfg["lanes"])[as_str(d["lane"])])["family"]

    # -- the answer ----------------------------------------------------------------------------------------------------------------------
    def emit(self, outcome: str | None, **kw: Json) -> int:
        self.out = answer.result(outcome, **kw)
        return 0

    def call(self) -> dict[str, Json]:
        """The call, end to end: the contract 4 answer object, validated by the caller (api.py) or printed by `go`."""
        self.go()
        return self.out

    def refuse(self, outcome: str, say: str, retry_after: float | None, **who: Json) -> int:
        """An answer given without launching a worker; history keeps it too, so refusals are countable."""
        a, call_id = self.a, getattr(self.a, "call_id", None)
        ff = health_ledger.failure_fields(outcome, "", say, retry_after)
        env.history_add(
            hist.RefusalRow(
                ts=env.now(),
                call_id=call_id,
                outcome=outcome,
                fingerprint=as_opt_str(ff.get("fingerprint")),
                say=as_opt_str(ff.get("say")),
                until=as_num(ff.get("until")),
                role=a.role,
                task=getattr(a, "task", None) or "",
                lane=as_opt_str(who.get("lane")),
                model=as_opt_str(who.get("model")),
                resume=bool(getattr(a, "resume", None)),
            )
        )
        return self.emit(outcome, say=say, retry_after=retry_after, call_id=call_id, transcript_status="not_launched", **who, **self.extra)

    # -- the call --------------------------------------------------------------------------------------------------------------------------
    def go(self) -> int:
        try:
            if os.environ.get("DELEGATE_DEPTH"):
                return self.refuse("caller", "DELEGATE_DEPTH is set: a delegated worker never delegates further", None)
            try:
                codex_policy.admit_request(getattr(self.a, "writer_exec_allow", []), tuple(getattr(self.a, "engine_only", None) or ()))
            except (ValueError, OSError) as error:
                return self.refuse("bad_request", str(error), None)
            return self._go()
        except codex_policy.ExecAllowError as error:
            return self.refuse("bad_request", str(error), None)
        except StateUnreadable as e:  # a state file from another version: needs the owner, and nothing was launched
            return self.refuse("crash", str(e), None)
        except TimeoutError as e:  # state lock held too long: transient, so stop with a retry time (error means permanent)
            return self.refuse("lock", str(e), env.now() + decide.busy_jitter())

    def _go(self) -> int:
        d, lanes, warnings, t = decide.decision(self.a, self.cfg, self.unattended, apply=True)
        if warnings:
            self.extra["warnings"] = warnings
        for key in ("notice", "warning"):
            if d.get(key):
                self.extra[key] = d[key]
        if d.get("warning"):
            self.log("warning: " + as_str(d["warning"]))
        if d["action"] in ("error", "stop"):
            return self._stopped(d, lanes, t)
        h = how_of(d)
        codex_policy.require_writer_mode(obj(d["how"]), getattr(self.a, "writer_exec_allow", []))
        who = {k: d.get(k) for k in IDENTITY}
        who["family"] = self._family(d)
        if not self.unattended:
            ni = [n["what"] for n in cockpit.needs_input(lanes)]
            if ni:
                self.extra["needs_input"] = ni
        call_id = getattr(self.a, "call_id", None)
        if h.kind not in profiles.REGISTRY and h.kind != "agent_tool":
            return self.refuse("setup", f"no launcher for runner kind {h.kind!r}: route.py has codex, opencode and claude_p", None, **who)
        if h.kind == "agent_tool":
            return self.emit(
                None,
                **who,
                call_id=call_id,
                transcript_status="unsupported",
                agent_model=h.model,
                brief_prefix=SECRET_RULE + " " + GIT_RULES,
                cwd=h.cwd,
                **self.extra,
            )
        brief = self._brief()
        if not brief.strip():
            return self.emit("caller", **who, call_id=call_id, say="empty brief: pass it on stdin or with --brief FILE", **self.extra)
        self.git_before = git.state(h.cwd)
        res = self._run(d, lanes, t, who, brief)
        if isinstance(res, dict) and res.get("outcome") == "schema_invalid" and not self.a.resume:
            res = self._reroute(res, brief)
        return self.emit(as_opt_str(res.pop("outcome", None)), **res) if isinstance(res, dict) else res

    def _brief(self) -> str:
        if self.given_brief is not None:
            return self.given_brief
        return Path(self.a.brief).read_text(encoding="utf-8", errors="replace") if self.a.brief else sys.stdin.read()

    def _reroute(self, res: dict[str, Json], brief: str) -> dict[str, Json] | int:
        """One fresh attempt after the re-ask failed; each attempt has already kept its own history and usage."""
        pair = (as_str(res["lane"]), as_str(res["model"]))
        d, lanes, warnings, t = decide.decision(self.a, self.cfg, self.unattended, frozenset((pair,)), apply=True)
        if (
            d["action"] != "run"
            or (d["lane"], d["model"]) == pair
            or how_of(d).kind == "agent_tool"
            or (getattr(self.a, "writer_exec_allow", []) and how_of(d).kind != "codex")
        ):
            res["say"] = (
                as_str(res["say"]) + "; no reroute: " + as_str(d.get("warning") or d.get("say") or "no other executable lane/model ready")
            )
            return res
        if warnings:
            self.extra["warnings"] = warnings
        self.extra.pop("warning", None)
        if d.get("warning"):
            self.extra["warning"] = d["warning"]
            self.log("warning: " + as_str(d["warning"]))
        who = {k: d.get(k) for k in IDENTITY}
        who["family"] = self._family(d)
        return self._run(d, lanes, t, who, brief)

    def _stopped(self, d: dict[str, Json], lanes: dict[str, Lane], t: float) -> int:
        a = self.a
        if d["action"] == "error":
            return self.refuse("caller", as_str(d["error"]), None)
        if d.get("outcome"):  # --resume on a lane that is out, benched or held
            return self.refuse(as_str(d["outcome"]), as_str(d["say"]), as_num(d.get("retry_after")), lane=d["lane"])
        holds, S = HoldBook(env.load_state().holds), env.settings_of(self.cfg)
        backs = [
            x
            for x in [ln.back_at(S, holds.covering(ln.name, a.role, t)) for ln in lanes.values()]
            + [b.until for ln in lanes.values() for b in ln.benched.values()]
            if x
        ]
        retry = min(backs) if backs else None
        if not self.unattended and d.get("ask_user"):
            self.extra.update(ask_user=d["ask_user"], ask_kind="decision")
        if d.get("reason") == "busy":
            return self.refuse("busy", as_str(d["say"]), as_num(d["retry_after"]), lane=d.get("lane"))
        if d.get("reason") == "engine_only_unenforced" and getattr(a, "only_family", None):
            return self.refuse("engine_only_unenforced", as_str(d["say"]), None)
        return self.refuse("no_lane", as_str(d["say"]), retry)

    def _run(self, d: dict[str, Json], lanes: dict[str, Lane], t: float, who: dict[str, Json], brief: str) -> dict[str, Json] | int:
        a, h = self.a, how_of(d)
        rid = str(uuid.uuid4())
        lane = lanes[as_str(d["lane"])]
        # A limit refusal mid-run lasts until the time its message names, else the soonest window reset (else an hour).
        resets = [(lane.week or 0, lane.week_reset), (lane.five or 0, lane.five_reset)]
        d["limit_reset"] = min(
            (r for _, r in resets if r and r > t), default=None
        )  # a guess: the soonest reset (too early costs one refused call, too late days)
        cap = lane.slots(env.settings_of(self.cfg))
        canary_due = bool(lane.canary.get(as_str(d["model"]))) and h.kind in profiles.REGISTRY
        silence_s = self.idle_s or watch.LIMITS[watch.CLI_OF_KIND[h.kind]]["silence_s"]
        lease = RunLease(rid, a.role, a.task, as_str(d["lane"]), as_str(d["model"]), cap, canary_due, silence_s)
        no = lease.claim()
        if no:
            return self.refuse(no[0], no[1], env.now() + decide.busy_jitter(), **who)
        lease.keep_alive()
        hooks, launched = self._hooks(rid, lease, d)
        fam = as_str(who["family"])
        git_before, t0 = self.git_before, time.time()
        t_from = file_size(harnesses.find_transcript(a.resume, fam)) if a.resume else 0
        res: dict[str, Json]
        try:
            res = self._launch(d, brief, rid, t, hooks, canary_due)
        except Exception as e:  # a launcher bug is an error object, not a stack trace
            res = {"outcome": "crash", "say": f"{type(e).__name__}: {e}"}
        except (
            SystemExit
        ) as e:  # SIGTERM / SIGHUP to this process: the supervisor stopped the worker's tree first; the caller still gets a typed answer
            if not isinstance(e.code, int) or e.code <= 128:
                raise
            res = {"outcome": "killed", "say": f"route.py got signal {e.code - 128}; its worker was stopped first"}
        finally:
            lease.finish(hooks.stops)
        return self._finish(res, d, lane, who, rid, lease, hooks, launched, cap, (t0, t_from, git_before))

    def _hooks(self, rid: str, lease: RunLease, d: dict[str, Json]) -> tuple[RunHooks, dict[str, Json]]:
        launched: dict[str, Json] = {}
        hooks = RunHooks(idle_s=self.idle_s, unattended=self.unattended)
        ref_rec = RefRecord(
            lane=as_str(d["lane"]),
            model=as_str(d["model"]),
            effort=as_str(d["effort"]),
            mode=as_str(d["mode"]),
            cap=as_num(d.get("cap")),
            rung=as_opt_int(d.get("rung")),
            fallback=as_opt_bool(d.get("fallback")),
            fallback_reason=as_opt_str(d.get("fallback_reason")),
            first_lane=as_opt_str(d.get("first_lane")),
        )

        def worker_started(w: procs.Worker) -> None:
            """The worker runs in its own process group (pgid = pid), so a SIGKILL on route.py leaves it running: say where it is, before
            any
            work, on stderr and in the lease (status --json `running`), so the caller can kill the group itself."""
            self.log(f"delegate: worker pid={w.pid} pgid={w.pgid} run_id={rid}")
            launched.update(pid=w.pid, pgid=w.pgid, start=w.start)
            lease.worker_started(w.pid, w.start)
            if self.on_started:
                self.on_started(rid, w)

        def keep_ref(ref: str) -> None:
            """Remember the ref for `--resume` whatever the outcome."""

            def keep(s: StateDoc) -> None:
                s.refs[ref] = ref_rec
                for k in list(s.refs)[:-200]:
                    s.refs.pop(k)

            env.update_state(keep)

        self.keep_ref = keep_ref

        def ref_seen(ref: str) -> None:
            """The vendor revealed its session id: store it, stamp the lease, and print it on stderr (the engine reads `delegate: ref=`)
            before any work is lost."""
            keep_ref(ref)
            self.log(f"delegate: ref={ref} run_id={rid}")
            lease.stamp_ref(ref)

        hooks.started, hooks.beat, hooks.ref = worker_started, lease.stamp_event, ref_seen
        return hooks, launched

    # -- the launch ladder: canary, network retry, schema re-ask
    # ------------------------------------------------------------------------------
    def _launch(
        self, d: dict[str, Json], brief: str, rid: str, t: float, hooks: RunHooks, canary_due: bool
    ) -> dict[str, Json]:
        a = self.a

        def launch_one(b: str, a_: env.Args) -> dict[str, Json]:
            return launch.launch_worker(d, b, a_, rid, t, self.cfg, hooks)

        res = self._canary(launch_one, d, a) if canary_due else None  # the one probe before full traffic; None = it passed
        res = res or launch_one(brief, a)
        if res.get("outcome") == "network" and not res.pop("started", False) and net.net_up(as_str(d["lane"])):
            res = launch_one(
                brief, a
            )  # dropped before the vendor had a session and the net is back: nothing to resume, nothing lost, so run it again, once
        if res.get("outcome") is None and a.schema:
            res = self._schema(res, launch_one)
        res.pop("started", None)  # the launcher's own bookkeeping, whichever launch (first, re-ask) produced `res`
        res.pop("answered", None)
        return res

    def _canary(self, launch_one: Callable[[str, env.Args], dict[str, Json]], d: dict[str, Json], a: env.Args) -> dict[str, Json] | None:
        """The pair's bench ended (or its lane's limit did): one 30 s probe before full traffic. -> None when it answered (a `done` row in
        history ends
        the ladder), else the failed result, which is the answer to the caller: the run's own history row then starts the next rung."""
        res = launch_one(CANARY_BRIEF, argparse.Namespace(**dict(vars(a), resume=None, schema=None, timeout=CANARY_TIMEOUT_S)))
        if res.get("outcome") is None:
            env.history_add(hist.CanaryRow(ts=env.now(), run_id=str(uuid.uuid4()), lane=as_str(d["lane"]), model=as_str(d["model"])))
            return None
        if res["outcome"] == "timeout":  # a probe that did not answer in time is hung: `timeout` is never counted, `hung` is
            res.update(
                outcome="hung",
                retry_after=env.now() + 60,
                say=f"canary: {d['lane']}/{d['model']} did not answer within {CANARY_TIMEOUT_S}s",
            )
        else:
            res["say"] = "canary failed: " + as_str(res.get("say"))
        return res

    def _schema(self, res: dict[str, Json], launch_one: Callable[[str, env.Args], dict[str, Json]]) -> dict[str, Json]:
        """delegate enforces the schema: one re-ask in the same thread, then schema_invalid."""
        a = self.a
        schema: Json = json.loads(Path(a.schema).read_text(encoding="utf-8"))
        why = "the answer is not JSON" if res.get("data") is None else answer.schema_problem(res["data"], schema)
        if why and res.get("ref"):
            again = launch_one(
                f"Your final answer does not match the required JSON schema: {why}. Reply again with only the JSON object.",
                argparse.Namespace(**dict(vars(a), resume=res["ref"])),
            )
            tok = [x for x in (as_opt_obj(res.get("tokens")), as_opt_obj(again.get("tokens"))) if x]
            again["tokens"] = {k: sum(as_num(x.get(k)) or 0 for x in tok) for k in ("in", "cached", "out")} if tok else None
            again["acct"] = accounting.merge(as_opt_obj(res.get("acct")), as_opt_obj(again.get("acct")))
            again["cost"] = (as_num(res.get("cost")) or 0) + (as_num(again.get("cost")) or 0)
            again["cumulative"] = again.get("cumulative") or res.get("cumulative")
            again["denied"] = [*arr(res.get("denied")), *arr(again.get("denied"))]
            res = again
            why = (
                None
                if res.get("outcome")
                else "the answer is not JSON"
                if res.get("data") is None
                else answer.schema_problem(res["data"], schema)
            )
        if why and res.get("outcome") is None:
            res.update(outcome="schema_invalid", say=f"the answer does not match the schema: {why}", schema_problem=why)
        return res

    # -- the end: history, usage, the answer
    # ----------------------------------------------------------------------------------------------------
    def _finish(
        self,
        res: dict[str, Json],
        d: dict[str, Json],
        lane: Lane,
        who: dict[str, Json],
        rid: str,
        lease: RunLease,
        hooks: RunHooks,
        launched: dict[str, Json],
        cap: int | None,
        started: tuple[float, int, dict[str, str] | None],
    ) -> dict[str, Json]:
        a, extra = self.a, self.extra
        t0, t_from, git_before = started
        fam, cwd = as_str(who["family"]), how_of(d).cwd
        err = as_str(res.pop("stderr", ""))
        if err:
            self.log(err[-2000:])
        done = res.get("outcome") is None
        lane_name, ref = as_str(d["lane"]), as_opt_str(res.get("ref"))
        if done and lane_name in ("CLAUDE_SUBSCRIPTION", "OPENAI_SUBSCRIPTION"):
            usage.auth_cache().remember(lane_name, True, "a worker run succeeded", env.now())
        if ref:  # every outcome: a stop, a failure and a timeout can all be resumed
            with contextlib.suppress(Exception):
                self.keep_ref(ref)
        secs = round(time.time() - t0, 1)
        transcript = harnesses.find_transcript(ref, fam)
        detail = as_str(res.pop("detail", ""))
        if detail:
            res["first_error"] = detail
        history_row(self.a, res, d, lane, rid, lease, cap, (ref, transcript, secs, done, detail))
        info = transcript_info(transcript, fam, t_from)
        ac = as_opt_obj(res.pop("acct", None))
        res.pop("cumulative", None)
        tokens = as_opt_obj(res.get("tokens"))
        usage_rec: dict[str, Json] = {
            "tokens": dict(tokens, **accounting.token_fields(ac)) if tokens else None,
            "cost": res.get("cost", 0),
            "secs": secs,
            "turns": res.pop("turns", None),
            "context_k": res.pop("context_k", None),
            "answer_bytes": len(as_str(res.get("text")).encode("utf-8")),
            **accounting.fields(ac, ref, time.time()),
        }
        if res.get("warnings"):  # the launcher's own (net_after_answer) join the router's
            extra["warnings"] = [*arr(extra.get("warnings")), *arr(res.pop("warnings"))]
        res.update(
            **who,
            run_id=rid,
            secs=secs,
            git_violation=git.changes(git_before, git.state(cwd)),
            context={"instructions": [str(f) for f in decide.repo_instructions(cwd)], "env_keys": sorted(env.child_env().keys())},
            transcript=transcript,
            call_id=getattr(a, "call_id", None),
            usage=usage_rec,
            transcript_info=info,
            transcript_status="ok" if info else "ref_unresolvable" if res.get("ref") else "died_before_session_id",
            **extra,
        )
        return worker_ended(res, hooks, launched)
