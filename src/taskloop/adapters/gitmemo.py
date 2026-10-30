"""The read-only git answers the port remembers while the files they come from are as they were (the engine asks the same few dozen per
run and a process costs ~14 ms each): a ref, HEAD, the branch, the merge base, the common dir, the origin url. The file system vouches:
an entry holds the signature of every file the answer comes from, and a changed signature is a miss."""

import os
import re
from pathlib import Path
from typing import Any

from taskloop.adapters.gitrepo import Dirs, Sig, git_dirs, is_dir_sig, sig
from taskloop.contracts.env import Env

COMMON_ARGS = ("rev-parse", "--path-format=absolute", "--git-common-dir")
BAD_NAME = re.compile(r"[~^@:{}*?\\[\s]|\.\.|\.lock$|^-|^[0-9a-f]{4,40}$")
COMMON_DIR_MEMO: dict[Any, str] = {}  # (resolved cwd, sig of its .git entry) -> the absolute git common dir
REF_MEMO: dict[Any, tuple[tuple[Sig, ...], str]] = {}  # (git dir, args) -> (sigs of every file the answer comes from, answer)


def config_key(env: Env, path: str | Path) -> tuple[Any, ...] | None:
    """What decides every `git config` answer for the checkout at `path`, as the file system shows it: its `.git`, each config file git
    reads for it, and the GIT_ environment that moves them. None when `path` is no plain checkout (nothing is to be cached then)."""
    dirs = git_dirs(path)
    if not dirs:
        return None
    gd, common, dot_git = dirs
    home = Path(env.get("HOME") or os.path.expanduser("~"))
    xdg = Path(env.get("XDG_CONFIG_HOME") or (home / ".config"))
    files = [
        gd / "config.worktree",
        common / "config",
        common / "config.worktree",
        home / ".gitconfig",
        xdg / "git" / "config",
        Path("/etc/gitconfig"),
        Path("/opt/homebrew/etc/gitconfig"),
        Path("/usr/local/etc/gitconfig"),
    ]
    skip = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")
    gitvars = (*sorted((k, v) for k, v in env.vars.items() if k.startswith("GIT_") and k not in skip), ("HOME", str(home)))
    return (str(path), is_dir_sig(dot_git), tuple(sig(f) for f in files), gitvars)


def ref_files(args: tuple[str, ...], dirs: Dirs) -> list[Path] | None:
    """The files a `git rev-parse`, `symbolic-ref` or `merge-base` of ref names reads (loose refs, HEAD, packed-refs); None when it is a
    question the memo does not know (a revision expression, a sha that may be a prefix)."""
    gd, common, _ = dirs
    if args == ("symbolic-ref", "--short", "-q", "HEAD"):
        return [gd / "HEAD"]
    if len(args) == 2 and args[0] == "rev-parse":
        names = [args[1]]
    elif len(args) == 4 and args[:3] == ("rev-parse", "--verify", "-q"):
        names = [args[3]]
    elif len(args) == 3 and args[0] == "merge-base":
        names = list(args[1:])
    else:
        return None
    files = [common / "packed-refs", common / "shallow"]
    for raw in names:
        name = raw.removesuffix("^{commit}").removesuffix("^{tree}")
        if not name or BAD_NAME.search(name):
            return None
        if name == "HEAD":
            files.append(gd / "HEAD")
            try:
                head = (gd / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                return None
            if head.startswith("ref:"):
                files.append(common / head[4:].strip())
            continue
        files += [common / (pre + name) for pre in ("", "refs/", "refs/tags/", "refs/heads/", "refs/remotes/")]
        files.append(common / "refs" / "remotes" / name / "HEAD")
    return files


def memo_key(env: Env, args: tuple[str, ...], cwd: str) -> tuple[Any, tuple[Sig, ...] | None, str | None]:
    """(key, sigs, a remembered answer): the memo entry a question maps to, if it is one the file system can vouch for."""
    if args == ("remote", "get-url", "origin"):
        ck = config_key(env, cwd)  # the url comes from config only (insteadOf included)
        key = ("get-url", ck) if ck else None
        return key, None, COMMON_DIR_MEMO.get(key) if key else None
    dirs = git_dirs(cwd) if args and args[0] in ("rev-parse", "symbolic-ref", "merge-base") else None
    if dirs and args == COMMON_ARGS:
        key = (str(Path(cwd).resolve()), is_dir_sig(dirs[2]))
        return key, None, COMMON_DIR_MEMO.get(key)
    files = ref_files(args, dirs) if dirs else None
    if dirs and files:
        rk = (str(dirs[0]), args)
        sigs = tuple(sig(f) for f in files)  # taken before git runs: a change during it shows next time
        hit = REF_MEMO.get(rk)
        return rk, sigs, hit[1] if hit and hit[0] == sigs else None
    return None, None, None


def remember(key: Any, sigs: tuple[Sig, ...] | None, args: tuple[str, ...], out: str) -> None:
    """Keep the answer of a question `memo_key` mapped (a missing ref is an answer too, until its file appears)."""
    if key is not None and sigs is None and out:
        COMMON_DIR_MEMO[key] = out
    elif key is not None and sigs is not None and (out or "--verify" in args):
        REF_MEMO[key] = (sigs, out)
