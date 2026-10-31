"""Delegate request, engine-only advisory brief, and write-stop diagnostics."""

import json
from typing import TYPE_CHECKING

from taskloop.adapters import delegate as dg
from taskloop.app.run.blocked import refuse_over_cap
from taskloop.contracts import log as rec
from taskloop.contracts.delegate import RunRequest
from taskloop.domain.checks import planref
from taskloop.domain.lanes import pin
from taskloop.domain.prompts.write import ENGINE_ONLY_ADVISORY

if TYPE_CHECKING:
    from taskloop.app.run.engine import Engine
    from taskloop.app.run.worker_call import Call


def request(e: Engine, c: Call, live: str, timeout_s: int, idle_s: int) -> RunRequest:
    """Only a pinned write may ask delegate to treat the engine-only guard as advisory."""
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
        engine_only=recipes,
        engine_only_advisory=bool(only_family and recipes),
    )


def brief(c: Call, req: RunRequest) -> str:
    """Include the advisory sentence in the prompt cap before anything spawns."""
    text = c.text
    if req.engine_only_advisory:
        text += ENGINE_ONLY_ADVISORY.format(recipes=", ".join(f"just {r}" for r in req.engine_only))
        refuse_over_cap(c.node, c.role, text)
    return text


def note_write_stop(e: Engine, c: Call, ans: dg.Answer) -> None:
    """Keep the actual argv and full delegate diagnostics for a pinned writer's stop."""
    res = ans.res
    if c.node == "write" and res.stop is not None and res.stop.reason in pin.STOP_REASONS:
        e.log.emit(rec.Note(text="write delegate stop: " + json.dumps({
            "argv": ans.argv, "stop": ans.raw, "say": res.say, "text": res.text,
            "first_error": res.first_error, "trace": ans.trace,
        })))
