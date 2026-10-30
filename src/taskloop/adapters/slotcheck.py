"""Is git at a slot the slot's own checkout? A core.worktree or core.bare in the shared .git/config points every slot's git at
another folder (lifesim-1mm); read as ambient config has it, unpinned, as a worker's or check's git would see it."""
from pathlib import Path
from typing import Any

from taskloop.adapters import gitmemo, gitrepo
from taskloop.contracts.env import Env
from taskloop.contracts.ports import Git

_MEMO: dict[tuple[Any, ...], tuple[str, str] | None] = {}  # (slot, what the config files and environment are now) -> tree_problem's answer


def _config_origin(ambient: Git, wt: str | Path) -> tuple[str, str]:
    """(where core.worktree is set and to what, core.bare's value): the last of each key wins, as `--get` does."""
    origin = bare = ""
    for e in ambient.config_entries(str(wt), r"^core\.(worktree|bare)$"):
        if e.key.lower() == "core.worktree":
            origin = f"{e.where}\t{e.value}" if e.value else e.where
        elif e.key.lower() == "core.bare":
            bare = e.value
    return origin.strip(), bare


def tree_problem(wt: str | Path, ambient: Git, env: Env) -> tuple[str, str] | None:
    """(what is wrong, the owner's fix) when git at `wt`, asked through the unpinned port `ambient` (as ambient config has it), is not
    that checkout; else None.
    Two git calls, none while the config files are as they were: a run asks eleven times."""
    key = gitmemo.config_key(env, wt)
    if key and key in _MEMO:
        return _MEMO[key]
    out = _problem(wt, ambient)
    if key:
        _MEMO[key] = out
    return out


def _problem(wt: str | Path, ambient: Git) -> tuple[str, str] | None:
    common, top = ambient.common_dir(str(wt)), ambient.toplevel(str(wt))  # core.bare=true has no top level: the message needs what is left
    repo = str(Path(common or ".").parent)
    origin, bare = _config_origin(ambient, wt)
    if origin:
        where = origin.split("\t")[0].replace("file:", "")
        return (f"core.worktree is set ({origin.replace(chr(9), ' = ', 1)})",
                "core.worktree redirects every worktree of this repo to another folder. Remove it: "
                f"`git config --unset core.worktree` in {repo} (it was set in {where}), then rerun.")
    if bare.strip().lower() == "true":
        return ("core.bare is true",
                "core.bare=true in the repo's config makes git refuse the work tree. Fix: `git config core.bare false` "
                f"in {repo}, then rerun.")
    if not top or not gitrepo.same_dir(top, wt):
        return (f"git's top-level folder is {top or '(none)'}, not the slot {wt}",
                f"Something redirects git away from the slot. Check `git config --show-origin --list` in {repo} for "
                f"core.worktree or core.bare; `git config --unset core.worktree` in {repo} if set.")
    return None
