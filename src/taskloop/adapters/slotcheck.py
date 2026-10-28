"""Is git at a slot the slot's own checkout? A core.worktree or core.bare in the shared .git/config points every slot's git at
another folder (lifesim-1mm); read as ambient config has it, unpinned, as a worker's or check's git would see it."""
import os
import subprocess
from pathlib import Path

from taskloop.adapters import gitrepo

_MEMO: dict[str, tuple[str, str] | None] = {}  # (slot, what the config files and environment are now) -> tree_problem's answer


def _git(wt: str | Path, *args: str) -> str:
    clean = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")}
    r = subprocess.run(["git", "-C", str(wt), *args], env=clean, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def _config_origin(wt: str | Path) -> tuple[str, str]:
    """(where core.worktree is set and to what, core.bare's value): the last of each key wins, as `--get` does."""
    origin = bare = ""
    for ln in _git(wt, "config", "--show-origin", "--get-regexp", r"^core\.(worktree|bare)$").splitlines():
        where, _, kv = ln.partition("\t")
        k, _, v = kv.partition(" ")
        if k.lower() == "core.worktree":
            origin = f"{where}\t{v}" if v else where
        elif k.lower() == "core.bare":
            bare = v
    return origin.strip(), bare


def tree_problem(wt: str | Path) -> tuple[str, str] | None:
    """(what is wrong, the owner's fix) when git at `wt`, read as ambient config has it, is not that checkout; else None.
    Two git calls, none while the config files are as they were: a run asks eleven times."""
    key = gitrepo.config_key(wt)
    if key and key in _MEMO:
        return _MEMO[key]
    out = _problem(wt)
    if key:
        _MEMO[key] = out
    return out


def _problem(wt: str | Path) -> tuple[str, str] | None:
    both = _git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir", "--show-toplevel").split("\n")
    if len(both) == 2:
        common, top = both
    else:  # one of the two fails (core.bare=true has no top level): ask for each alone, as the message needs what is left
        common, top = _git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir"), ""
    repo = str(Path(common or ".").parent)
    origin, bare = _config_origin(wt)
    if origin:
        where = origin.split("\t")[0].replace("file:", "")
        return (f"core.worktree is set ({origin.replace(chr(9), ' = ', 1)})",
                "core.worktree redirects every worktree of this repo to another folder. Remove it: "
                f"`git config --unset core.worktree` in {repo} (it was set in {where}), then rerun.")
    if bare.strip().lower() == "true":
        return ("core.bare is true",
                "core.bare=true in the repo's config makes git refuse the work tree. Fix: `git config core.bare false` "
                f"in {repo}, then rerun.")
    top = top or _git(wt, "rev-parse", "--show-toplevel")
    if not top or not gitrepo.same_dir(top, wt):
        return (f"git's top-level folder is {top or '(none)'}, not the slot {wt}",
                f"Something redirects git away from the slot. Check `git config --show-origin --list` in {repo} for "
                f"core.worktree or core.bare; `git config --unset core.worktree` in {repo} if set.")
    return None
