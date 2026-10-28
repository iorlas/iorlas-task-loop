"""The files a check's cache key reads: a git tree's listing, the ignored files under some globs, a file's digest."""
import hashlib
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

BIG = 16 * 1024 * 1024  # an ignored input bigger than this counts by size, not content


def tree_files(wt: str, tree: str, env: Mapping[str, str]) -> dict[str, str]:
    """{path: "mode type sha"} for a git tree, from `git ls-tree -r -z`."""
    r = subprocess.run(["git", "ls-tree", "-r", "-z", tree], cwd=wt, env=dict(env), capture_output=True, check=False)
    out: dict[str, str] = {}
    for ent in r.stdout.decode("utf-8", "surrogateescape").split("\0"):
        meta, _, path = ent.partition("\t")
        if path:
            out[path] = meta
    return out


def ignored_files(wt: str, spec: Sequence[str], env: Mapping[str, str]) -> list[str]:
    """Ignored (untracked, gitignored) files in the worktree under the git pathspecs `spec` (all of them when empty)."""
    r = subprocess.run(["git", "ls-files", "-z", "-o", "-i", "--exclude-standard"] + (["--", *spec] if spec else []),
                       cwd=wt, env=dict(env), capture_output=True, check=False)
    return [p for p in r.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def file_digest(path: str) -> str:
    h = hashlib.sha1()
    try:
        size = os.path.getsize(path)
        if size > BIG:
            return f"big:{size}"
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return "gone"
    return h.hexdigest()


def origin_url(wt: str, env: Mapping[str, str]) -> str:
    """`git config --get remote.origin.url`, '' when there is none."""
    r = subprocess.run(["git", "config", "--get", "remote.origin.url"], cwd=wt, env=dict(env), capture_output=True, check=False, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def repo_key(wt: str, env: Mapping[str, str]) -> str:
    """One name per repo, shared by its slots and worktrees: the origin url, else the common git dir."""
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=wt, env=dict(env),
                            capture_output=True, check=False, text=True)
    ident = origin_url(wt, env) or (common.stdout.strip() if common.returncode == 0 else "") or str(wt)
    return "{}-{}".format(re.sub(r"[^\w.-]+", "_", Path(ident.rstrip("/")).name)[:40] or "repo",
                      hashlib.sha1(ident.encode("utf-8", "surrogateescape")).hexdigest()[:10])


def lock_holders(wt: str, named: Sequence[str]) -> str:
    """Pids that have the project lockfile open (lsof), '' when none or lsof is missing. The path is one the output names, else
    Temp/UnityLockfile under the tree."""
    cands = [Path(n) if os.path.isabs(n) else Path(wt) / n for n in named] + sorted(Path(wt).glob("*/Temp/UnityLockfile"))
    for f in cands:
        if not f.exists():
            continue
        try:
            r = subprocess.run(["lsof", "-t", str(f)], capture_output=True, check=False, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return ""
        pids = [x for x in r.stdout.split() if x.isdigit()]
        if pids:
            return ",".join(pids)
    return ""


def read_lines(path: str | Path, n: int = 2000) -> list[str]:
    """The first n lines of a text file, [] when it cannot be read."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [ln.rstrip("\n") for _, ln in zip(range(n), f, strict=False)]
    except OSError:
        return []
