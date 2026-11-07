"""One repo key (tl-19hr): the three spellings an older tl wrote under repos/, artifacts/ and in factory.db become `ids.loop_key`.

The old spellings are hashes, so they are found the way they were made: from each registered repo's folder, its origin url and its
git common dir (`old_spellings`). What a repo no longer in repos.json left behind goes to retired/, never deleted. Pure listing here;
adapters/layout_migrate.py runs the moves and journals them."""
import hashlib
import re
from collections.abc import Callable, Iterable
from pathlib import Path

from taskloop.adapters.layout_paths import retired_dir
from tlkernel.gitport import Git
from tlkernel.ids import loop_key
from tlkernel.paths import ConfigDir
from tlkernel.slots import git_probe

OLD_KEY = re.compile(r".+-[0-9a-f]{10}|[0-9a-f]{12}")  # <name>-<10 hex of the url>; 12 hex of the common dir
SPLIT = ("slots", "slot-state", "decisions")  # folders that hold one entry per slot or decision: merged entry by entry
Pair = tuple[Path, Path]


def stale(name: str) -> bool:
    return OLD_KEY.fullmatch(name) is not None


def _slot_name(origin: str) -> str:
    """The name bead_env gave a slot-state folder (frozen here: it must reproduce what the older tl wrote, whatever repo_id becomes)."""
    name = Path(origin.rstrip("/")).name
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name.removesuffix(".git"))[:40] or "repo"


def _sha(text: str, n: int) -> str:
    return hashlib.sha1(text.encode("utf-8", "surrogateescape")).hexdigest()[:n]


def old_spellings(git: Git, repo: str) -> list[str]:
    """Every old key the repo at `repo` can have written: the checks' (origin url, else common dir, else folder), the slot state's
    (the origin's name and hash, else the worktree's), and the 12-hex common-dir key."""
    common = git.common_dir(repo)
    origin = git_probe(lambda: git.config_get(repo, "remote.origin.url"), "")
    ident = origin or common or repo
    checks = "{}-{}".format(re.sub(r"[^\w.-]+", "_", Path(ident.rstrip("/")).name)[:40] or "repo", _sha(ident, 10))
    remote = git_probe(lambda: git.remote_url(repo, "origin"), "") or repo
    state = f"{_slot_name(remote)}-{_sha(remote, 10)}"
    return list(dict.fromkeys([checks, state, *([_sha(common, 12)] if common else [])]))


def keymap(git: Git, repos: Iterable[str]) -> dict[str, str]:
    """{old key: loop_key} for the registered repo folders that still exist."""
    out: dict[str, str] = {}
    for repo in repos:
        if Path(repo).is_dir():
            out.update({old: loop_key(repo) for old in old_spellings(git, repo)})
    return out


def home(cfg: ConfigDir, key: str, keys: dict[str, str]) -> Path:
    """The repo folder a state of old key `key` belongs in: the repo's one key, retired/ when the repo is unknown."""
    if key in keys:
        return cfg.repo_dir(keys[key])
    return retired_dir(cfg) / "repos" / key if stale(key) else cfg.repo_dir(key)


def left_over(cfg: ConfigDir) -> list[Path]:
    """The folders of repos/ and artifacts/, and the shared/ notes, still named in an old spelling (found without asking git)."""
    found: list[Path] = []
    for parent, folders in ((cfg.repos_dir(), True), (cfg.artifact_store(), True), (cfg.shared("").parent, False)):
        found += [p for p in sorted(parent.glob("*")) if p.is_dir() == folders and stale(p.name if folders else p.stem)]
    return found


def moves(cfg: ConfigDir, keys: dict[str, str]) -> list[Pair]:
    """Where the old-keyed folders go: into the repo's one key (slots, slot-state and decisions entry by entry, the rest as they are)."""
    out: list[Pair] = []
    for d in left_over(cfg):
        if d.is_file():
            out.append((d, cfg.shared(keys[d.stem]) if d.stem in keys else retired_dir(cfg) / "shared" / d.name))
        elif d.parent == cfg.artifact_store():
            out.append((d, cfg.artifact_store() / keys[d.name] if d.name in keys else retired_dir(cfg) / "artifacts" / d.name))
        elif d.name not in keys:
            out.append((d, retired_dir(cfg) / "repos" / d.name))
        else:
            dst = cfg.repo_dir(keys[d.name])
            for child in sorted(d.iterdir()):
                kids = sorted(child.iterdir()) if child.name in SPLIT and child.is_dir() else None
                out += [(k, dst / child.name / k.name) for k in kids] if kids is not None else [(child, dst / child.name)]
    return out


def rekey_rows(keys: dict[str, str], run: Callable[[str, tuple[str, ...]], int]) -> int:
    """Rewrite the old keys in factory.db: the durations (kv `durations:<key>`) and the check receipts (check_pass.repo_key). `run`
    executes one statement and returns the rows it changed. A row the new key already holds wins; the old one (a cache) is dropped."""
    n = 0
    for old, new in keys.items():
        for sql, args in (
            ("UPDATE OR IGNORE kv SET k=? WHERE k=?", (f"durations:{new}", f"durations:{old}")),
            ("DELETE FROM kv WHERE k=?", (f"durations:{old}",)),
            ("UPDATE OR IGNORE check_pass SET repo_key=? WHERE repo_key=?", (new, old)),
            ("DELETE FROM check_pass WHERE repo_key=?", (old,)),
        ):
            n += run(sql, args)
    return n
