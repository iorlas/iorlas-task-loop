"""Slot profile selection, directory rules and priority defaults (node: slots)."""
import os
import sys
from pathlib import Path
from typing import Any, NamedTuple

from tlkernel import config, profile_at
from tlkernel.bead import Bead
from tlkernel.config import EngineConfig, RepoProfile, SlotsConfig
from tlkernel.gitport import Git
from tlkernel.paths import TASK_EXCLUDE
from tlkernel.slottable import WORKTREE, SlotSource, SlotTable

from tlslots.effects import Effects
from tlslots.env import DEFAULT_PRIO


def profile(repo: str, base: str | None, git: Git) -> dict[str, Any]:
    """The repo's loop profile (.task-loop.json, parsed). With `base` (a ref such as origin/main), the copy committed there, so a pushed
    rule counts after a fetch even when nobody pulled the checkout; the working tree only when `base` does not resolve here (no remote).
    A file missing on the base is {}: committed wins."""
    return profile_source(repo, base, git)[0]



def profile_source(repo: str, base: str | None, git: Git) -> tuple[dict[str, Any], str]:
    """The profile and its exact commit, or an empty commit for the working-tree fallback."""
    return profile_at.source(git, repo, base)



def load_profile(data: Any) -> RepoProfile:
    """A parsed .task-loop.json as a RepoProfile; an unknown key or a wrong type exits, naming it. A retired key is said once."""
    try:
        return profile_at.typed(data, say_to=sys.stderr)
    except config.ConfigError as e:
        print(f"task-loop: {e}", file=sys.stderr)
        raise SystemExit(os.EX_CONFIG) from e



class SelectedProfile(NamedTuple):
    cfg: RepoProfile
    base: str
    commit: str
    slots_source: str


def cfg_source(repo: str, git: Git) -> tuple[RepoProfile, str, str]:
    """The selected profile, base hint and pinned commit (empty for a local fallback)."""
    selected = selected_profile(repo, git)
    return selected.cfg, selected.base, selected.commit


def selected_profile(repo: str, git: Git) -> SelectedProfile:
    """The selected typed profile, revision and origin of its effective slot count. Bad profiles exit loudly."""
    try:
        local = profile(repo, None, git)
        engine = local.get("engine") if isinstance(local, dict) else None
        hint = engine.get("base") if isinstance(engine, dict) else None
        base = hint if isinstance(hint, str) else EngineConfig().base
        data, commit = profile_source(repo, base, git)
        cfg = load_profile(data)
        slots = data.get("slots") if isinstance(data, dict) else None
        source = "profile" if isinstance(slots, dict) and "count" in slots else "default"
        return SelectedProfile(cfg, base, commit, source)
    except config.ConfigError as err:
        print(f"task-loop: {err}", file=sys.stderr)
        raise SystemExit(os.EX_CONFIG) from err



def load_cfg(repo: str, git: Git) -> EngineConfig:
    """The `engine` block of the repo's .task-loop.json as committed on the base branch, defaults for what it leaves out. The base is
    itself a key: the working tree names it, then the base's copy is read. A caller fetches first."""
    return cfg_source(repo, git)[0].engine



def profile_slots(repo: str, git: Git | None = None) -> SlotsConfig:
    """The `slots` block of the repo's loop profile. With `git`, as committed on the base ref (what the loops read, `cfg_source`: a stale
    checkout does not change the count); without, the working tree's copy (no git to ask; prefer passing one)."""
    if git is not None:
        return cfg_source(repo, git)[0].slots
    try:
        return local_profile(repo).slots
    except (OSError, ValueError):
        # Keep slots off when the profile cannot be read safely.
        return SlotsConfig(count=0)



def slot_source(repo: str, git: Git, *, fx: Effects) -> SlotSource:
    """The slot count the loops use (the profile on the base ref, as `cfg_source` reads it), this machine's host and the slot folders on
    disk. A bad profile exits (cfg_source says so); a caller that must not exit answers for it."""
    profile_, base, commit = cfg_source(repo, git)
    cfg = profile_.slots
    root = str(Path(slot_dir(repo, "x", cfg)).parent)
    return SlotSource(host=fx.hostname(), count=cfg.count, source=base if commit else WORKTREE, sha=commit, dirs=slot_dirs(root), root=root)



def slot_dirs(root: str) -> frozenset[str]:
    """The names of the slot folders in `root` (no process: a directory listing)."""
    try:
        return frozenset(d.name for d in Path(root).iterdir() if d.is_dir())
    except OSError:
        return frozenset()



def slot_dir(repo: str, name: str, cfg: SlotsConfig) -> str:
    root = cfg.dir
    return str(Path(root if os.path.isabs(root) else os.path.join(repo, root)) / name)



def slot_excludes(repo: str, cfg: SlotsConfig) -> tuple[str, ...]:
    """The exclude lines for the slot folder (a path under the repo; one outside it needs none) and the scratch folder."""
    d = Path(slot_dir(repo, "x", cfg)).parent
    return (str(d.relative_to(repo)) + "/", TASK_EXCLUDE) if d.is_relative_to(repo) else (TASK_EXCLUDE,)



def exclude_local(git: Git, repo: str, *patterns: str) -> None:
    """Keep the loop's own folders out of `git add -A` in every repo, without touching its tracked .gitignore."""
    common = git.common_dir(repo)
    if not common:
        return
    f = Path(common) / "info" / "exclude"
    f.parent.mkdir(parents=True, exist_ok=True)
    have = f.read_text(encoding="utf-8") if f.exists() else ""
    add = [p for p in patterns if p not in have.split()]
    if add:
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(("\n" if have and not have.endswith("\n") else "") + "\n".join(add) + "\n")



def prio_of(bead: Bead | None) -> int:
    """The priority number of a bead (0 = P0), DEFAULT_PRIO when it has none."""
    return bead.priority if bead and bead.priority is not None else DEFAULT_PRIO


def local_profile(repo: str) -> RepoProfile:
    """The local typed profile with the slots command's configuration exit status."""
    try:
        return profile_at.typed_in(repo, say_to=sys.stderr)
    except config.ConfigError as e:
        print(f"task-loop: {e}", file=sys.stderr)
        raise SystemExit(os.EX_CONFIG) from e


def status_footer(repo: str, git: Git, table: SlotTable) -> tuple[str, ...]:
    """The effective slot count and the table's configuration revision, including empty tables."""
    selected = selected_profile(repo, git)
    return (
        f"slots: {selected.cfg.slots.count} ({selected.slots_source})",
        f"(slots.count {table.configured} from {table.source}{' ' + table.source_sha[:7] if table.source_sha else ''})",
    )


def configured_slots(repo: str, git: Git) -> tuple[int, str]:
    """The doctor's effective slot count and its source label."""
    selected = selected_profile(repo, git)
    return selected.cfg.slots.count, selected.slots_source
