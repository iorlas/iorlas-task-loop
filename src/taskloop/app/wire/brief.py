"""The facts of `tl status --brief` and the handoff, read from the stores (LoopFiles, AskStore, the slot beads, the catalog and the pin):
no reader of its own."""
import json
from pathlib import Path

from taskloop.adapters import pidcheck
from taskloop.adapters.ident import config_dir
from taskloop.app.doctor import profiles
from taskloop.app.loop.files import LoopFiles
from taskloop.app.release import catalog, pins
from taskloop.app.slots import marks
from taskloop.app.wire import asks as wire_asks
from taskloop.app.wire import slots as wslots
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import loop_key
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure, Git
from taskloop.contracts.stores import ReposStore
from taskloop.domain.brief import AskLine, Brief, LoopLine, status_json, status_lines

RECENT = 5


def running_version(plugin_root: Path) -> str:
    try:
        return str(json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def slot_lines(repo: str, who: Identity, now: float) -> tuple[str, ...]:
    """One line per slot of this machine. A repo without bd or slots has none."""
    try:
        beads = wslots.slot_beads(repo, who)
    except (SystemExit, OSError, ValueError, BdFailure):
        return ()
    out: list[str] = []
    for b in beads:
        held = marks.hold_of(b, now)
        state = f"held by {marks.held_by(b)}" if held else (f"claimed by {b.assignee}" if b.assignee else "free")
        out.append(f"{b.title.split()[-1]}: {state}")
    return tuple(out)


def build(repo: str, plugin_root: Path, now: float, who: Identity | None = None) -> Brief:
    """`who`: ask bd for the slots too, as that actor (one subprocess; the hooks that must be fast leave it out)."""
    cfg = ConfigDir(config_dir())
    files = LoopFiles(cfg, loop_key(repo), pidcheck.pid_alive, lambda: now)
    loops = files.live()
    last = files.last_exit()
    beats = [st.t or st.started for st in loops] or [st.t or st.started for st in files.died()]
    last_beat = max([*beats, float(str(last.get("t") or 0))])
    asks = tuple(AskLine(a.bead, a.kind, a.decision, a.t) for a in wire_asks.store().live() if not a.repo or a.repo == repo)
    recent = tuple(f"{i.rec.bead} {i.rec.outcome.value} ({i.rec.minutes} min)" for i in files.log_rows(RECENT).items)
    pin = pins.read_pin().task_loop
    return Brief(
        repo=repo, now=now,
        loops=tuple(LoopLine(st.pid, st.started, st.bead or "", st.slot or "", st.version) for st in loops),
        last_beat=last_beat, last_exit=str(last.get("reason") or ""), asks=asks,
        slots=slot_lines(repo, who, now) if who else (), recent=recent,
        version=running_version(plugin_root), installed=catalog.installed_version("task-loop"), pinned=(pin or ""))


def handoff_file(repo: str) -> Path:
    return ConfigDir(config_dir()).handoff(loop_key(repo))


def status_text(repo: str, plugin_root: Path, now: float, as_json: bool, who: Identity, git: Git) -> str:
    b = build(repo, plugin_root, now, who)
    # a bad profile is its repo's row
    red = profiles.red_rows(git, sorted({repo, *profiles.registered(ReposStore(ConfigDir(config_dir())))}))
    if as_json:
        return json.dumps({**status_json(b), "red": red}, ensure_ascii=False)
    return "\n".join([*red, *status_lines(b)])
