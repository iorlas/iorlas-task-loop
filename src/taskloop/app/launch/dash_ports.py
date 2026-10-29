"""The dashboard's ports, made from the engine code: the read-only facts the package taskloop_dash may not import (slot beads,
the waiting line, a repo's config, the installed versions, the run reflections) and bd through the engine's adapter."""

import dataclasses
import shutil
from collections.abc import Callable
from typing import Any

from taskloop.adapters.bd import BdStore
from taskloop.app.asks.intake import Intake
from taskloop.app.release import catalog
from taskloop.app.report import reflect
from taskloop.app.track.trail import now
from taskloop.app.wire import asks as wire_asks
from taskloop.app.wire import slots as wslots
from taskloop.contracts.ask import Ask, AskAction
from taskloop.domain.asks import text as asktext
from taskloop_dash.env import Ports


def quiet(fn: Callable[..., Any], default: Any) -> Callable[..., Any]:
    """A port that never raises: tl.bd exits when bd is not on PATH."""
    def call(*a: Any) -> Any:
        try:
            return fn(*a)
        except (Exception, SystemExit):
            return default
    return call


def store(repo: str) -> BdStore:
    """The dashboard's bd: the engine's typed adapter (--actor, --json), the one process site."""
    if not shutil.which("bd"):
        raise OSError(2, "bd is not installed")
    return BdStore("tl-dash", repo or None, timeout=30)


def answer(repo: str, bead: str, action: AskAction, text: str, amend: bool) -> tuple[Ask | None, str]:
    """The dashboard's answer is `tl answer`'s: the same Intake (record, bead opened, receipt comment), only `by` is "dash"."""
    return Intake(wire_asks.store(), store(repo), now, "dash").answer(bead, action, text, amend)


def slot_beads(repo: str) -> list[dict[str, Any]]:
    return [dataclasses.asdict(b) for b in wslots.slot_beads(repo)]


def load_cfg(repo: str) -> dict[str, Any]:
    return dataclasses.asdict(wslots.load_cfg(repo))


def ports() -> Ports:
    """`python3 -m taskloop_dash --ports taskloop.app.launch.dash_ports:ports`: the dashboard builds its ports from the engine's code."""
    return Ports(store=store, answer=answer, ask_text=asktext.markdown,
                 slot_beads=quiet(slot_beads, []),
                 waiting_line=quiet(wslots.waiting_line, []),
                 load_cfg=quiet(load_cfg, {"pick_label": "auto", "skip_labels": []}),
                 reflections=quiet(reflect.view, {}),
                 installed_versions=quiet(lambda: sorted(catalog.cache_dirs("task-loop")), []))
