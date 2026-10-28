"""The dashboard's ports, made from the flat engine code: the read-only facts the package taskloop_dash may not import (slot beads,
the waiting line, a repo's config, the installed versions, the run reflections) and bd through the engine's adapter. tl.py passes
its own modules in (`tl.dash_ports`), so this file imports none of them."""

import dataclasses
import shutil
import types
from collections.abc import Callable
from typing import Any

from taskloop.adapters.bd import BdStore
from taskloop_dash.env import Ports


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


def make_ports(tl: Any, engine: Any, reflect_digest: Any) -> Ports:
    return Ports(bd=bd,
                 slot_beads=quiet(lambda repo: [dataclasses.asdict(b) for b in tl.slot_beads(repo)], []),
                 waiting_line=quiet(lambda repo: tl.waiting_line(repo), []),
                 load_cfg=quiet(lambda repo: dataclasses.asdict(engine.load_cfg(repo)), {"pick_label": "auto", "skip_labels": []}),
                 reflections=quiet(lambda hours: reflect_digest.view(hours), {}),
                 installed_versions=quiet(lambda: sorted(tl.cache_dirs("task-loop")), []))
