"""Read-only git questions about a checkout, answered from the file system when it can vouch for the answer (the engine asks the same few
dozen per run and a process costs ~14 ms each), plus the fetch that survives a ref-lock race and the repo's main checkout."""
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from taskloop.adapters.gitenv import git_env, pinned_env

Sig = tuple[int, ...] | None
Dirs = tuple[Path, Path, Path]  # git dir, common dir, the `.git` entry of the checkout

COMMON_ARGS = ("rev-parse", "--path-format=absolute", "--git-common-dir")
BAD_NAME = re.compile(r"[~^@:{}*?\\[\s]|\.\.|\.lock$|^-|^[0-9a-f]{4,40}$")
# another process fetching into the same repo (worktrees share refs/remotes) at the same moment: the ref is then where it should be, the
# fetch only lost the lock (race test, tl-bxk.11.1: 150 of 180 fetches at once failed so)
REF_RACE = re.compile(r"incorrect old value|cannot lock ref|unable to update local ref|Unable to create '[^']*\.lock'")
COMMON_DIR_MEMO: dict[Any, str] = {}  # (resolved cwd, sig of its .git entry) -> the absolute git common dir
REF_MEMO: dict[Any, tuple[tuple[Sig, ...], str]] = {}  # (git dir, args) -> (sigs of every file the answer comes from, answer)


def sig(path: str | Path) -> Sig:
    """What a file is now, as the file system says: (inode, dev, mtime ns, size); None when it is missing. A ref or lock file is
    replaced by a rename, so a changed ref always changes this."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_dev, st.st_mtime_ns, st.st_size)


def is_dir_sig(p: str | Path) -> Sig:
    """A `.git` directory changes its mtime with every lock file; only which directory it is counts. A `.git` file (a slot) is stable."""
    try:
        st = os.stat(p)
    except OSError:
        return None
    return (st.st_ino, st.st_dev) if os.path.isdir(p) else (st.st_ino, st.st_dev, st.st_mtime_ns, st.st_size)


def git_dirs(cwd: str | Path) -> Dirs | None:
    """The dirs of a plain checkout read from the file system, or None when `cwd` is none or uses a ref backend this reads nothing of."""
    pin = pinned_env(cwd)
    gd = pin.get("GIT_DIR")
    if not gd:
        return None
    gd_path = Path(gd)
    common = gd_path
    try:
        c = (gd_path / "commondir").read_text(encoding="utf-8", errors="replace").strip()
        common = (gd_path / c).resolve()
    except OSError:
        pass
    if (common / "reftable").exists():
        return None
    return gd_path, common, Path(pin["GIT_WORK_TREE"]) / ".git"


def config_key(path: str | Path) -> tuple[Any, ...] | None:
    """What decides every `git config` answer for the checkout at `path`, as the file system shows it: its `.git`, each config file git
    reads for it, and the GIT_ environment that moves them. None when `path` is no plain checkout (nothing is to be cached then)."""
    dirs = git_dirs(path)
    if not dirs:
        return None
    gd, common, dot_git = dirs
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))
    files = [gd / "config.worktree", common / "config", common / "config.worktree", home / ".gitconfig", xdg / "git" / "config",
             Path("/etc/gitconfig"), Path("/opt/homebrew/etc/gitconfig"), Path("/usr/local/etc/gitconfig")]
    skip = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")
    env = (*sorted((k, v) for k, v in os.environ.items() if k.startswith("GIT_") and k not in skip), ("HOME", str(home)))
    return (str(path), is_dir_sig(dot_git), tuple(sig(f) for f in files), env)


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


def memo_key(args: tuple[str, ...], cwd: str | None) -> tuple[Any, tuple[Sig, ...] | None, str | None]:
    """(key, sigs, a remembered answer): the memo entry a question maps to, if it is one the file system can vouch for."""
    if cwd is None and args == COMMON_ARGS and not any(k in os.environ for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")):
        try:
            here: str | None = os.getcwd()  # the process's own checkout: nothing is pinned, so only plain checkouts count
        except OSError:  # its folder is gone: git answers "" below
            here = None
        dirs = git_dirs(here) if here else None
        key = (here, is_dir_sig(dirs[2])) if dirs and here else None
        return key, None, COMMON_DIR_MEMO.get(key) if key else None
    if not cwd:
        return None, None, None
    if args == ("remote", "get-url", "origin"):
        ck = config_key(cwd) if git_dirs(cwd) else None  # the url comes from config only (insteadOf included)
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


def git(*args: str, cwd: str | Path | None = None) -> str:
    """The stripped stdout of `git ARGS` ("" when it fails), pinned to `cwd`'s checkout; read-only questions come from the memo."""
    cwd_s = str(cwd) if cwd is not None else None
    key, sigs, known = memo_key(args, cwd_s)
    if known is not None:
        return known
    r = subprocess.run(["git", *args], cwd=cwd_s, env=git_env(cwd_s) if cwd_s else None, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", check=False)
    out = r.stdout.strip() if r.returncode == 0 else ""
    if key is not None and sigs is None and out:
        COMMON_DIR_MEMO[key] = out
    elif key is not None and sigs is not None and (out or "--verify" in args):  # a missing ref is an answer too, until its file appears
        REF_MEMO[key] = (sigs, out)
    return out


def fetch(cwd: str | Path | None = None, tries: int = 5) -> subprocess.CompletedProcess[str]:
    """`git fetch -q origin`, tried again while it loses a ref lock to a concurrent fetch; the last CompletedProcess."""
    cwd_s = str(cwd) if cwd is not None else None
    r = subprocess.CompletedProcess([], 0, "", "")
    for i in range(tries):
        r = subprocess.run(["git", "fetch", "-q", "origin"], cwd=cwd_s, env=git_env(cwd_s) if cwd_s else None, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", check=False)
        if r.returncode == 0 or not REF_RACE.search(r.stderr or ""):
            break
        time.sleep(0.1 * (i + 1))
    return r


def repo_root(cwd: str | Path | None = None) -> str:
    """The main checkout of the repo (shared by all its worktrees), so every worktree maps to one repo."""
    common = git(*COMMON_ARGS, cwd=cwd)
    if common:
        p = Path(common)
        return str(p.parent if p.name == ".git" else p)
    return git("rev-parse", "--show-toplevel", cwd=cwd) or str(Path(cwd or os.getcwd()).resolve())
