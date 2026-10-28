"""The dashboard's ports, made from the flat engine code: the read-only facts the package taskloop_dash may not import (slot beads,
the waiting line, a repo's config, the installed versions, the run reflections) and bd through the engine's adapter."""

import dataclasses
import shutil
from collections.abc import Callable
from typing import Any

from taskloop.adapters.bd import BdStore
from taskloop.app.asks.intake import Intake
from taskloop.app.track.trail import now
from taskloop.app.wire import asks as wire_asks
from taskloop.contracts.ask import Ask, AskAction
from taskloop.domain.asks import text as asktext
from taskloop_dash.env import Ports
from taskloop.app.release import catalog
from taskloop.app.wire import slots as wslots
import reflect_digest


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


def ports() -> Ports:
    """`python3 -m taskloop_dash --ports dash_wiring:ports`: the dashboard process builds its ports from the flat code on its path, and
    `tl ask` in a terminal uses the same."""
    return Ports(store=store, answer=answer, ask_text=asktext.markdown,
                 slot_beads=quiet(lambda repo: [dataclasses.asdict(b) for b in wslots.slot_beads(repo)], []),
                 waiting_line=quiet(lambda repo: wslots.waiting_line(repo), []),
                 load_cfg=quiet(lambda repo: dataclasses.asdict(wslots.load_cfg(repo)), {"pick_label": "auto", "skip_labels": []}),
                 reflections=quiet(lambda hours: reflect_digest.view(hours), {}),
                 installed_versions=quiet(lambda: sorted(catalog.cache_dirs("task-loop")), []))
