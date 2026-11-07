"""The facts of `tl status --brief` and the handoff, read from the stores (LoopFiles, AskStore, the slot beads, the catalog and the pin):
no reader of its own."""
import hashlib
import json
from pathlib import Path

from tlkernel.bd_errors import BdCommandFailure
from tlkernel.beadsport import BdFailure
from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import loop_key
from tlkernel.paths import ConfigDir
from tlkernel.rowstores import ReposStore
from tlkernel.slots import SlotView
from tlslots.config import status_footer

from taskloop.adapters import pidcheck
from taskloop.adapters.ident import claude_dir, config_dir
from taskloop.adapters.locks import resource_holders
from taskloop.app.doctor import profiles
from taskloop.app.loop.files import LoopFiles
from taskloop.app.release import catalog, pins
from taskloop.app.wire import asks as wire_asks
from taskloop.app.wire import slots as wslots
from taskloop.domain.brief import AskLine, Brief, LoopLine, ResourceLine, status_json, status_lines

RECENT = 5


def running_version(plugin_root: Path) -> str:
    try:
        return str(json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def shim_sha256(config: Path) -> str:
    """The sha256 of <config>/bin/tl, the shim every session runs; '' when it is not there."""
    try:
        return hashlib.sha256((config / "bin" / "tl").read_bytes()).hexdigest()
    except OSError:
        return ""


def slot_lines(repo: str, who: Identity, now: float, git: Git) -> tuple[str, ...]:
    """One line per slot of the slot table (the same rows the dash lists): config from the base ref, state from `now`. A repo without bd
    or a readable profile has none."""
    try:
        table = wslots.slot_table(repo, who, git, now)
        return tuple(line_of(v) for v in table.slots if v.state != "retiring") + status_footer(repo, git, table)
    except (BdCommandFailure, SystemExit, OSError, ValueError, BdFailure):
        return ()


def line_of(v: SlotView) -> str:
    what = {"free": "free", "held": f"held by {v.holder}: {v.held_reason}", "running": f"running {v.bead}".rstrip(),
            "setup": f"starting {v.bead}", "claimed": f"claimed by {v.holder or '?'}, no live run",
            "dead": f"claimed by {v.holder or '?'}, folder missing"}.get(v.state, v.state)
    return f"{v.id}: {what}" + (" (above slots.count)" if v.beyond_count else "")


def held_resources(cfg: ConfigDir) -> tuple[ResourceLine, ...]:
    """Every taken unit of the lease table (the machine's, all repos): the holder's label is `bead:check`."""
    out = []
    for name, rec in resource_holders(cfg):
        bead, _, check = rec.holder.partition(":")
        out.append(ResourceLine(name, bead, check, rec.t))
    return tuple(out)


def build(repo: str, plugin_root: Path, now: float, env: Env, who: Identity | None = None, git: Git | None = None) -> Brief:
    """`who`: ask bd for the slots too, as that actor (one subprocess; the hooks that must be fast leave it out)."""
    cfg = ConfigDir(config_dir(env))
    files = LoopFiles(cfg, loop_key(repo), pidcheck.pid_alive, lambda: now)
    loops = files.live()
    last = files.last_exit()
    beats = [st.t or st.started for st in loops] or [st.t or st.started for st in files.died()]
    last_beat = max([*beats, float(str(last.get("t") or 0))])
    asks = tuple(AskLine(a.bead, a.kind, a.decision, a.t) for a in wire_asks.store(cfg).live() if not a.repo or a.repo == repo)
    recent = tuple(f"{i.rec.bead} {i.rec.outcome.value} ({i.rec.minutes} min)" for i in files.log_rows(RECENT).items)
    pin = pins.read_pin(env).task_loop
    return Brief(
        repo=repo, now=now,
        loops=tuple(LoopLine(st.pid, st.started, st.bead or "", st.slot or "", st.version) for st in loops),
        last_beat=last_beat, last_exit=str(last.get("reason") or ""), asks=asks,
        slots=slot_lines(repo, who, now, git) if who and git else (), resources=held_resources(cfg), recent=recent,
        version=running_version(plugin_root), installed=catalog.installed_version(claude_dir(env)), pinned=(pin or ""),
        shim_sha256=shim_sha256(cfg.root))


def handoff_file(repo: str, env: Env) -> Path:
    return ConfigDir(config_dir(env)).handoff(loop_key(repo))


def status_text(repo: str, plugin_root: Path, now: float, as_json: bool, env: Env, who: Identity, git: Git) -> str:
    b = build(repo, plugin_root, now, env, who, git)
    # a bad profile is its repo's row
    red = profiles.red_rows(git, sorted({repo, *profiles.registered(ReposStore(ConfigDir(config_dir(env))))}))
    if as_json:
        return json.dumps({**status_json(b), "red": red}, ensure_ascii=False)
    return "\n".join([*red, *status_lines(b)])
