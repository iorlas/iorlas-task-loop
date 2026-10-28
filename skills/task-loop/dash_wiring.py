"""The dashboard's ports, made from the flat engine code: the read-only facts the package taskloop_dash may not import (slot beads,
the waiting line, a repo's config, the installed versions, the run reflections) and bd through the engine's adapter."""

import dataclasses
import shutil
import types
from collections.abc import Callable
from typing import Any

from taskloop.adapters.bd import BdStore
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


def bd(repo: str | None, *args: str, timeout: int = 30) -> types.SimpleNamespace:
    """The dashboard's bd: the engine's adapter (--actor, --json), one process site."""
    if not shutil.which("bd"):
        raise OSError(2, "bd is not installed")
    r = BdStore("tl-dash", repo, timeout=timeout).passthrough(list(args))
    if r.code == 127:  # the adapter folds "bd cannot be run" into 127
        raise OSError(2, "bd cannot be run")
    return types.SimpleNamespace(returncode=r.code, stdout=r.out, stderr=r.err)


def ports() -> Ports:
    """`python3 -m taskloop_dash --ports dash_wiring:ports`: the dashboard process builds its ports from the flat code on its path, and
    `tl ask` in a terminal uses the same."""
    return Ports(bd=bd, ask_text=asktext.markdown,
                 slot_beads=quiet(lambda repo: [dataclasses.asdict(b) for b in wslots.slot_beads(repo)], []),
                 waiting_line=quiet(lambda repo: wslots.waiting_line(repo), []),
                 load_cfg=quiet(lambda repo: dataclasses.asdict(wslots.load_cfg(repo)), {"pick_label": "auto", "skip_labels": []}),
                 reflections=quiet(lambda hours: reflect_digest.view(hours), {}),
                 installed_versions=quiet(lambda: sorted(catalog.cache_dirs("task-loop")), []))
