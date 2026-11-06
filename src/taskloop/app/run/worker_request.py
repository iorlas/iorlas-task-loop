"""Delegate request, engine-only advisory brief, and write-stop diagnostics."""

import json
from typing import Protocol

from taskloop.adapters import childenv, ident
from taskloop.adapters import delegate as dg
from taskloop.adapters.check_files import repo_key
from taskloop.app.asks import trustroots
from taskloop.app.checks.runner import Checker
from taskloop.app.run.blocked import Blocked, refuse_over_cap
from taskloop.app.run.budget import Budget
from taskloop.app.run.call import Call
from taskloop.contracts import log as rec
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.delegate import RunRequest, ToolBinding
from taskloop.contracts.env import Env
from taskloop.contracts.ids import BeadId
from taskloop.contracts.plancheck import PlanData
from taskloop.contracts.ports import Beads, Git
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.asks.spec import AskSpec
from taskloop.domain.checks import planref
from taskloop.domain.lanes import pin
from taskloop.domain.prompts.write import ENGINE_ONLY_ADVISORY
from taskloop.stores.runlog import RunLog


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
    budget: Budget

    def blocked_for(self, why: str, kind: str, stop: object = None, spec: AskSpec | None = None, fix: bool = False) -> Blocked: ...


def request(e: RequestHost, c: Call, live: str, timeout_s: int, idle_s: int) -> RunRequest:
    """Only a pinned write may ask delegate to treat the engine-only guard as advisory."""
    if c.role == "reviewer":
        why = trustroots.refusal(e.git, e.wt, e.cfg.base, e.store.show(e.bead))
        if why:
            raise e.blocked_for(why, "ASK_DECISION", spec=askspecs.open_question(why, None, "decision"))
    only_family = pin.for_role(c.role, pin.families(e.cfg.writer_family, e.budget.labels))
    recipes = e.checker.split().engine_recipes(planref.stage_commands(e.plan_data, e.cfg)) if c.node == "write" else []
    return RunRequest(
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
        only_family=only_family,
        writer_exec_allow=e.cfg.writer_exec_allow if c.role == pin.PINNED_ROLE else [],
        engine_only=recipes,
        read_roots=list(e.cfg.writer_read_roots) if c.node == "write" else [],
        engine_only_advisory=bool(only_family and recipes),
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


def brief(c: Call, req: RunRequest) -> str:
    """Include the advisory sentence in the prompt cap before anything spawns."""
    text = c.text
    if req.engine_only_advisory:
        text += ENGINE_ONLY_ADVISORY.format(recipes=", ".join(f"just {r}" for r in req.engine_only))
        refuse_over_cap(c.node, c.role, text)
    return text


def note_write_stop(e: RequestHost, c: Call, ans: dg.Answer) -> None:
    """Keep the actual argv and full delegate diagnostics for a pinned writer's stop."""
    res = ans.res
    if c.node == "write" and res.stop is not None and res.stop.reason in pin.STOP_REASONS:
        e.log.emit(rec.Note(text="write delegate stop: " + json.dumps({
            "argv": ans.argv, "stop": ans.raw, "say": res.say, "text": res.text,
            "first_error": res.first_error, "trace": ans.trace,
        })))
