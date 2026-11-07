"""Delegate request, engine-only advisory brief, and write-stop diagnostics."""

import json
from typing import Final, Protocol

from tlasks import trustroots
from tlgate.domain import planref
from tlgate.runner import Checker
from tlkernel import askspecs, childenv
from tlkernel import lanecaps as caps
from tlkernel import log as rec
from tlkernel.askspec import AskSpec
from tlkernel.beadsport import Beads
from tlkernel.check_files import repo_key
from tlkernel.config import EngineConfig
from tlkernel.delegate import RunRequest, ToolBinding
from tlkernel.delegateport import Answer
from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.ids import BeadId
from tlkernel.plancheck import PlanData
from tlkernel.stop import Stop

from taskloop.adapters import ident
from taskloop.app.workers import writer_pin
from taskloop.app.workers.call import Call
from taskloop.domain.lanes import pin
from taskloop.stores.runlog import RunLog

ENGINE_ONLY_ADVISORY: Final = ("\nDo not run the engine-only recipes ({recipes}); the writer's harness may not deny them, "
                               "and the engine runs them after you.\n")


class Labelled(Protocol):
    labels: list[str]


class RequestHost(Protocol):
    """What building a delegate request reads of the run."""

    cfg: EngineConfig
    bead: BeadId
    wt: str
    store: Beads
    session: str
    plan_data: PlanData | None
    log: RunLog
    git: Git
    checker: Checker
    budget: Labelled

    def blocked_for(self, why: str, kind: str, stop: object = None, spec: AskSpec | None = None, fix: bool = False) -> Stop: ...


def request(e: RequestHost, c: Call, live: str, timeout_s: int, idle_s: int) -> RunRequest:
    """Only a pinned write may ask delegate to treat the engine-only guard as advisory."""
    if c.role == "reviewer":
        why = trustroots.refusal(e.git, e.wt, e.cfg.base, e.store.show(e.bead))
        if why:
            raise e.blocked_for(why, "ASK_DECISION", spec=askspecs.open_question(why, None, "decision"))
    # the reviewer is judged by the base's rules, not the branch's
    base_ref = e.git.rev_parse(e.wt, e.cfg.base) if c.role == "reviewer" else ""
    if c.role == "reviewer" and not base_ref:
        e.log.warn(f"the reviewer reads the work tree's instruction files: {e.cfg.base} does not resolve to a commit")
    prefer = writer_pin.prefer(e.budget.labels, c.role)
    recipes = e.checker.split().engine_recipes(planref.stage_commands(e.plan_data, e.cfg)) if c.node == "write" else []
    return RunRequest(
        role=c.role,
        brief_path="",
        cwd=str(c.cwd),
        schema_path="",
        parent=e.session,
        task=e.bead,
        title=f"{e.bead} · {c.node}: {c.title}",
        thread=c.thread,
        boundary=c.boundary,
        timeout_s=timeout_s,
        idle_s=idle_s,
        live_file=live,
        prefer=prefer,
        writer_exec=e.cfg.writer_exec if c.role == pin.PINNED_ROLE else False,
        reviewer_other_family=e.cfg.reviewer_other_family if c.role == "reviewer" else False,
        engine_only=recipes,
        instructions_ref=base_ref,
        engine_only_advisory=bool(prefer and recipes),
    )


class ToolHost(Protocol):
    """What binding the artifact_add server reads of the run."""

    bead: BeadId
    wt: str
    git: Git
    env: Env
    run_id: str
    live_n: int
    artifact_repo: str


def artifact_tool(e: ToolHost, c: Call) -> ToolBinding:
    """The artifact_add server for one worker call, visual or not. Its slot is in its argv: the repo, bead, run, stage and the call's
    number in this run (the attempt, so every delegate call has its own folder). `--cwd` is the worker's folder."""
    e.artifact_repo = e.artifact_repo or repo_key(e.git, e.wt)
    stage, attempt = c.step or c.node, e.live_n
    tl = ident.PLUGIN_ROOT / "skills" / "task-loop" / "tl.py"
    argv = [*childenv.script_argv(tl, e.env), "artifact-server", "--repo", e.artifact_repo, "--bead", str(e.bead), "--run", e.run_id,
            "--stage", stage, "--attempt", str(attempt), "--cwd", str(c.cwd)]
    return ToolBinding(name="factory", command=argv, bead=str(e.bead), run=e.run_id, stage=stage, attempt=attempt)


def refuse_over_cap(e: RequestHost, node: str, role: str, text: str) -> None:
    """Raise the Task fault (ASK_TICKET) when `text` is over its role's input cap; call it before a delegate call spawns."""
    over = caps.check(role, text)
    if over is not None:
        raise e.blocked_for(over.why(node), "ASK_TICKET", spec=askspecs.input_too_big(node, over.size, over.cap))


def brief(e: RequestHost, c: Call, req: RunRequest) -> str:
    """Include the advisory sentence in the prompt cap before anything spawns."""
    text = c.text
    if req.engine_only_advisory:
        text += ENGINE_ONLY_ADVISORY.format(recipes=", ".join(f"just {r}" for r in req.engine_only))
        refuse_over_cap(e, c.node, c.role, text)
    return text


def note_write_stop(e: RequestHost, c: Call, ans: Answer) -> None:
    """Keep the actual argv and full delegate diagnostics for a pinned writer's stop."""
    res = ans.res
    if c.node == "write" and res.stop is not None and res.stop.reason in pin.STOP_REASONS:
        e.log.emit(rec.Note(text="write delegate stop: " + json.dumps({
            "argv": ans.argv, "stop": ans.raw, "say": res.say, "text": res.text,
            "first_error": res.first_error, "trace": ans.trace,
        })))
