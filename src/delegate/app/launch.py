"""One worker, end to end: the harness for a runner kind builds its launch (`prepare_*`), the Supervisor runs it, the one ladder classifies
it and the
Settler applies the outcome (`launch_worker`). Also the rules every worker's prompt starts with and the guard hook it runs under."""

import contextlib
import dataclasses
import json
import shlex
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final, NamedTuple

from delegate.adapters import agent_runs, codex_account
from delegate.adapters.harness import classify, opencode_sandbox
from delegate.adapters.harness.base import Harness, LaunchInputs, LaunchSpec
from delegate.adapters.harness.claude import ClaudeHarness
from delegate.adapters.harness.codex import CodexHarness
from delegate.adapters.harness.opencode import OpenCodeHarness, Profile
from delegate.app import answer, codex_policy, decide, env, harnesses, net, settle, watch
from delegate.app.publish import LiveSink
from delegate.app.supervisor import LogWatcher, RunHooks, RunOutcome, Supervisor
from delegate.contracts import events as ev
from delegate.contracts.json_types import Json, as_num, as_opt_obj, as_opt_str, as_str, as_strs, obj
from delegate.contracts.state import StateDoc
from delegate.domain.cost import accounting
from delegate.domain.holds.book import HoldBook
from delegate.domain.policy import worker as policy
from delegate.domain.policy.matchers import heredoc_only_hit, secret_hit
from delegate.domain.policy.worker import EDIT_RULE, GIT_RULES, SECRET_RULE

DENIED_RULE = (
    "If a command is denied, that is a decision for the owner: do not retry or reword it; "
    "report the exact command in your final message and stop."
)
NO_SUBAGENTS_RULE = "Do not spawn sub-agents; do the work yourself."
ESCALATE_RULE = (
    "You run unattended. If a command fails because of the sandbox (network, files outside this directory, a system resource), "
    "request escalated permissions for that exact command once, with a one-line justification."
)
PREAMBLE = (
    SECRET_RULE
    + " You are a delegated worker. Do exactly the task in the brief. Do not delegate further and do not use the delegate skill. "
    + GIT_RULES
    + " "
    + EDIT_RULE
    + " "
    + DENIED_RULE
    + " Finish with a short report: what you changed or found, and the exit code and last lines of any check you ran."
)


def settler() -> settle.Settler:
    return settle.Settler(env.states(), net.net_up, env.now, decide.busy_jitter)


def guard_settings(read_only: bool | None, engine_only: tuple[str, ...] = ()) -> dict[str, Json]:
    """--settings for claude -p: delegate's PreToolUse hook (route.py guard), read-only for steps that may not write."""
    argv = [sys.executable, str(env.ENTRY), "guard"] + (["--read-only"] if read_only else [])
    argv += [f"--engine-only={x}" for x in engine_only] if not read_only else []
    argv += ["--config-dir", str(env.config_dir())]
    cmd = shlex.join(argv)
    return {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]}}


def codex_reset_now(t: float) -> float | None:
    """The reset of the Codex window a fresh reading shows full (>= 95%), else None."""
    res, _ = codex_account.rate_limits()
    rl = obj(obj(res).get("rateLimits"))
    full = [
        r
        for w in (obj(rl.get("primary")), obj(rl.get("secondary")))
        if (as_num(w.get("usedPercent")) or 0) >= 95 and (r := as_num(w.get("resetsAt")) or 0) > t
    ]
    return min(full) if full else None


def repo_instruction_text(cwd: str, cap: int = 32768) -> str:
    """--restricted keeps Claude from loading the repo's CLAUDE.md; Codex reads AGENTS.md. Both lanes get the same files
    (repo_instructions),
    capped like Codex's project_doc_max_bytes."""
    out, left = "", cap
    for f in decide.repo_instructions(cwd):
        with contextlib.suppress(OSError):
            body = f.read_text(encoding="utf-8", errors="replace")[:left]
            left -= len(body)
            out += f"\n\nRepository instructions ({f.name} in {f.parent}):\n{body}"
        if left <= 0:
            break
    return out


class Prep(NamedTuple):
    """The harness, its launch, and what the ladder needs from before the launch."""

    hx: Harness
    spec: LaunchSpec
    extra: dict[str, Json]


class How(NamedTuple):
    """The `how` of a decision (decide.how): what a step runs on."""

    kind: str
    cwd: str
    model: str
    write: bool
    read_only: bool | None
    sandbox: str
    cli: list[str]
    isolation: list[str]


def how_of(d: dict[str, Json]) -> How:
    h = obj(d["how"])
    read_only = h.get("read_only")
    return How(
        as_str(h["kind"]),
        as_str(h.get("cwd")),
        as_str(h.get("model")),
        bool(h.get("write")),
        read_only if isinstance(read_only, bool) else None,
        as_str(h.get("sandbox")),
        as_strs(h.get("cli")),
        as_strs(h.get("isolation")),
    )


def lane_gone_check(lane: str, since: float) -> Callable[[], str | None]:
    """-> a function: the words of a limit, credit or login mark another process set on `lane` after `since` (wall clock), else None. The
    worker
    still running there is burning an exhausted lane."""

    def gone() -> str | None:
        o = env.load_state().out.get(lane)
        if o and o.set >= since and o.until > env.now() and o.reason in ("limit", "credit", "logged_out"):
            return o.why or "lane marked out"
        return None

    return gone


def secret_in(e: ev.HarnessEvent) -> str | None:
    """The command a Cmd or CmdEnd event names a secret path in, else None (delegate polices the stream of the CLIs that have no hook).
    A secret name only inside a heredoc body is code being written, not a read: it does not stop the run."""
    return e.text if isinstance(e, ev.Cmd | ev.CmdEnd) and secret_hit(e.text) and not heredoc_only_hit(e.text) else None


def denied_items(hx: Harness, read_only: bool | None, engine_only: tuple[str, ...] = ()) -> list[dict[str, Json]]:
    """The `denied` items of a run, from the denials its harness reported. A git write the coordinator forbids, or a write on a read-only
    step, is
    delegate's policy, not the owner's call, and Claude's own record of it is dropped."""
    out = []
    for x in hx.evidence.denials:
        cmd = as_opt_str((x.input or {}).get("command"))
        if hx.kind == "claude" and policy.is_policy_denial(x.tool, x.input, bool(read_only), engine_only):
            continue
        kind = x.kind if x.kind != "policy" else "secret" if hx.kind == "opencode" and x.tool == "Bash" and secret_hit(cmd) else "policy"
        out.append(policy.denial_item(policy.denial(kind, x.tool, x.input)))
    return out


def prepare_codex(d: dict[str, Json], brief: str, a: env.Args, rid: str, t: float, cfg: dict[str, Json]) -> Prep | dict[str, Json]:
    h = how_of(d)
    role = d.get("role", getattr(a, "role", None))
    hold = HoldBook(env.load_state().holds).covering(as_str(d.get("lane")) or "OPENAI_SUBSCRIPTION", as_opt_str(role), t)
    if hold:
        return HoldBook.refusal(hold, "no worker was launched")
    exe = shutil.which("codex")
    if not exe:
        return {"outcome": "setup", "say": "codex CLI not found on PATH"}
    hx = CodexHarness(a.resume)
    spec = hx.launch_spec(
        LaunchInputs(
            exe=exe,
            cwd=h.cwd,
            model=h.model,
            effort=as_str(d["effort"]),
            sandbox=h.sandbox,
            out_file=str(env.config_dir() / f"codex-last-{rid[:8]}.txt"),
            env=decide.codex_env(env.child_env(), h.cwd, h.sandbox),
            cli=h.cli,
            access=decide.CODEX_ACCESS,
            isolation=h.isolation,
            schema=a.schema,
            resume=a.resume,
            prompt=" ".join(
                (
                    SECRET_RULE,
                    GIT_RULES,
                    EDIT_RULE,
                    NO_SUBAGENTS_RULE,
                    "" if getattr(a, "writer_exec_allow", []) else ESCALATE_RULE,
                    DENIED_RULE,
                )
            )
            + "\n\n"
            + brief,
        )
    )
    try:
        spec, hx.overlay = codex_policy.configure_writer(
            spec, getattr(a, "writer_exec_allow", []), env.config_dir(), tuple(getattr(a, "engine_only", None) or ())
        )
        before = (codex_account.thread_total(a.resume) or env.history_store().last_cumulative(a.resume)) if a.resume else None
    except BaseException:
        hx.cleanup()
        raise
    return Prep(hx, spec, {"before": before, "started": time.time()})  # wall clock, not env.now(): it is compared with file times


def prepare_claude(d: dict[str, Json], brief: str, a: env.Args, rid: str, t: float, cfg: dict[str, Json]) -> Prep | dict[str, Json]:
    """claude -p on the logged-in subscription (CLAUDE_SUBSCRIPTION, unattended)."""
    h = how_of(d)
    exe = shutil.which("claude")
    if not exe:
        return {"outcome": "setup", "say": "claude CLI not found on PATH"}
    hx = ClaudeHarness()
    spec = hx.launch_spec(
        LaunchInputs(
            exe=exe,
            cwd=h.cwd,
            model=h.model,
            effort=as_str(d["effort"]),
            prompt=brief,
            env=env.child_env(),
            schema=a.schema,
            resume=a.resume,
            session=rid,
            system=PREAMBLE + repo_instruction_text(h.cwd),
            settings=json.dumps(guard_settings(h.read_only, tuple(getattr(a, "engine_only", None) or ()))),
            write=h.write,
        )
    )
    return Prep(hx, spec, {})


def prepare_opencode(d: dict[str, Json], brief: str, a: env.Args, rid: str, t: float, cfg: dict[str, Json]) -> Prep | dict[str, Json]:
    """OpenCode headless runner for subscription and isolated free-only lanes."""
    h, lane = how_of(d), as_str(d["lane"])
    exe = OpenCodeHarness.find_exe()
    if not exe or not OpenCodeHarness.supported():
        return {"outcome": "setup", "say": f"{lane} needs macOS and the opencode CLI (route.py doctor)"}
    nested = opencode_sandbox.preflight()
    if nested:  # before any model token: the lane is out for a while, so the next call routes to the next lane
        settler().mark_out(lane, t + 3600, f"nested_sandbox: {nested}", t, "limit", "guess")
        return {
            "outcome": "setup",
            "say": f"nested_sandbox: {lane} commands cannot run here ({nested}); this process is already inside a sandbox. "
            "Rerun to use the next lane.",
        }
    if (
        lane == "ZAI_CODING_SUBSCRIPTION" and h.model not in harnesses.ZAI_MODELS
    ):  # pin subscription routing; never substitute the pay-as-you-go `zai` provider
        return {"outcome": "setup", "say": "Z.ai Coding Plan model must use the subscription provider."}
    rules = " ".join((SECRET_RULE, GIT_RULES, EDIT_RULE, NO_SUBAGENTS_RULE, opencode_sandbox.RULE, DENIED_RULE))
    if h.write and getattr(a, "engine_only", None):
        rules += f" Only the engine runs these recipes: {', '.join(a.engine_only)}. {policy.WRITER_RULE}"
    if not any((x / "AGENTS.md").is_file() for x in decide.repo_dirs(h.cwd)):
        rules += "\n\n" + repo_instruction_text(h.cwd)  # opencode reads AGENTS.md itself; CLAUDE.md only through what is turned off
    if a.schema:
        rules += "\n\nYour final message must be only a JSON object matching this JSON Schema:\n" + Path(a.schema).read_text(
            encoding="utf-8"
        )
    hx = OpenCodeHarness(harnesses.OC_PROFILES.get(lane, Profile()), env.config_dir())
    spec = hx.launch_spec(
        LaunchInputs(
            exe=exe,
            cwd=h.cwd,
            model=h.model,
            effort=as_str(d["effort"]),
            prompt=rules + "\n\n" + brief,
            env=env.child_env(),
            resume=a.resume,
            session=rid,
            write=h.write,
            engine_only=tuple(getattr(a, "engine_only", None) or ()),
        )
    )
    if lane == "DEEPSEEK_FREE" and not hx.free_model_ok(h.model, spec.env):  # fail closed if the exact free model or its zero price is gone
        hx.cleanup()
        until = t + 900
        settler().mark_out(lane, until, "exact free model unavailable or zero catalog price unverified", t, "limit", "guess")
        return {
            "outcome": "rate_limited",
            "retry_after": until,
            "say": "Free DeepSeek is unavailable or its zero price could not be verified; rerun to use the next configured lane.",
        }
    return Prep(hx, spec, {})


PREPARE: Final = {"codex": prepare_codex, "claude_p": prepare_claude, "opencode": prepare_opencode}
REF_FIELD: Final = {"codex": "thread", "claude_p": "session", "opencode": "session"}  # the agent-runs field the vendor's session id goes in
AGENT_KIND: Final = {"codex": "codex", "claude_p": "claude-p", "opencode": "opencode"}


def login_text(kind: str, lane: str) -> tuple[str, str]:
    """(the hint stored with a lane that is logged out, the text of the answer with {why})."""
    if kind == "codex":
        return "logged out: run `codex login`", "codex is not logged in: {why} (route.py doctor)"
    if kind == "claude_p":
        return "logged out: run `claude auth login`", "claude is not logged in: {why} (claude auth login)"
    hint = (
        "free OpenCode access refused; no paid credentials will be used"
        if lane == "DEEPSEEK_FREE"
        else "run `opencode auth login` and choose Z.AI Coding Plan; enter your Coding Plan key in your own terminal"
        if lane == "ZAI_CODING_SUBSCRIPTION"
        else "run `opencode auth login` (xAI, SuperGrok Subscription)"
    )
    return hint, f"{lane}: {hint}: {{why}}"


def codex_usage(res: dict[str, Json], x: dict[str, Json]) -> None:
    """Codex's usage is a thread's running total: keep this run's part, add the reviewer's tokens (its own child thread), and read the
    context size."""
    tokens = accounting.per_call(as_opt_obj(res["tokens"]), as_opt_obj(x["before"]))
    ref = as_opt_str(res["ref"])
    if ref:
        extra, n = codex_account.child_tokens(ref, (as_num(x["started"]) or 0) - 1)
        if n:
            base = tokens or {"in": 0, "cached": 0, "out": 0}
            tokens = {k: (as_num(base.get(k)) or 0) + extra[k] for k in extra}
    res.update(tokens=tokens, context_k=codex_account.context_k(ref), acct=accounting.codex(tokens))


def lane_cleared(lane: str) -> Callable[[StateDoc], object]:
    """The state change that drops the out-mark of `lane`."""

    def clear(s: StateDoc) -> object:
        return s.out.pop(lane, None)

    return clear


def launch_worker(
    d: dict[str, Json], brief: str, a: env.Args, rid: str, t: float, cfg: dict[str, Json], meta: dict[str, Json], hooks: RunHooks
) -> dict[str, Json]:
    """One worker, end to end: its harness builds the launch, the supervisor runs it, the one ladder settles it. -> dict[str, Json] of
    result fields."""
    kind = how_of(d).kind
    prep = PREPARE[kind](d, brief, a, rid, t, cfg)
    if isinstance(prep, dict):
        return prep
    try:
        return run_prepared(prep, d, a, rid, t, meta, hooks)
    finally:
        prep.hx.cleanup()


def run_prepared(
    prep: Prep, d: dict[str, Json], a: env.Args, rid: str, t: float, meta: dict[str, Json], hooks: RunHooks
) -> dict[str, Json]:
    """Use an already prepared harness; launch_worker owns cleanup even if publication or supervision raises."""
    h = how_of(d)
    lane = as_str(d["lane"])
    hx, spec, x = prep
    field = REF_FIELD[h.kind]

    def on_ref(ref: str) -> None:
        if hooks.ref:
            hooks.ref(ref)
        agent_runs.run(rid, **{field: ref})

    if hx.evidence.ref:
        on_ref(hx.evidence.ref)  # known before the first event: a resume, or claude's own --session-id
    agent_runs.run(
        rid,
        kind=AGENT_KIND[h.kind],
        lane=d["lane"],
        model=d["model"],
        cwd=h.cwd,
        started=t,
        status="running",
        **({field: hx.evidence.ref} if hx.evidence.ref else {}),
        **meta,
    )
    live = LiveSink(hx.kind, run_id=rid)
    live.start(
        lane=as_opt_str(d.get("lane")),
        model=as_opt_str(d.get("model")),
        effort=as_opt_str(d.get("effort")),
        role=as_opt_str(d.get("role") or getattr(a, "role", None)),
    )
    log = LogWatcher(hx.log_dir, classify.LIMIT_RE.search, hx.echoes_input) if hx.log_dir else None
    sup = Supervisor(
        hx,
        watch.CLI_OF_KIND[h.kind],
        dataclasses.replace(hooks, ref=on_ref),
        live,
        gone=lane_gone_check(lane, time.time()),
        log=log,
        policy=secret_in if hx.secret_event else None,
        net_up=lambda: net.net_up(lane),
    )
    out = sup.run(spec, a.timeout)
    hx.export(spec.env)
    with contextlib.suppress(
        Exception
    ):  # one history row per inter-event gap over watch.LONG_GAP_S (role "gap"): the health fold ignores it
        sup.dog.flush(env.history_add, lane, as_str(d["model"]), out.watch.why is None)
    return finish_run(hx, h, a, d, t, out, x)


def finish_run(hx: Harness, h: How, a: env.Args, d: dict[str, Json], t: float, out: RunOutcome, x: dict[str, Json]) -> dict[str, Json]:
    """The result dict of a finished supervised run: the CLI's own error is classified and applied, a clean run clears its lane."""
    lane = as_str(d["lane"])
    sm, w = out.summary, out.watch
    res: dict[str, Json] = dict(sm.res, stderr=out.err, denied=denied_items(hx, h.read_only, tuple(getattr(a, "engine_only", None) or ())))
    if h.kind == "codex":
        codex_usage(res, x)
    if out.stream_tail:
        res["stream_tail"] = out.stream_tail
    if w.why == "hung":
        res["hung_words"], res["hung_kind"] = w.words, w.kind
    facts = dict(sm.facts, watchdog=w.why, msg=w.msg, secret=out.secret)
    o = classify.classify(sm.rc, sm.vendor, sm.stderr, out.timed_out, sm.work, facts) if sm.check else None
    if (
        out.stop == "answer" and o and o.reason == "killed" and sm.stands and not out.timed_out
    ):  # we stopped it after its answer: the answer stands
        o = None
        res["warnings"] = ["answer_done_process_alive"]
    if out.net and (o is None or o.reason == "killed"):  # we stopped it because the network is down
        o = classify.Outcome("network", hx.evidence.transient, "event")
    if o:  # the CLI's own error or stderr, never the model's answer
        settler().apply(
            res,
            o,
            d,
            t,
            hx.kind,
            a,
            sm.rc,
            sm.tail,
            reset=(lambda: codex_reset_now(t)) if hx.kind == "codex" else None,
            login=login_text(h.kind, lane),
        )
    else:
        env.update_state(lane_cleared(lane))
        res.update(data=sm.data if sm.data is not None else answer.parse_data(sm.text, a.schema))
        if sm.warnings:
            res["warnings"] = sm.warnings
    return res
