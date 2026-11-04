"""The SessionStart hook: index the session id -> its transcript path. Must never fail the session."""
import contextlib
import json
import os
import shlex
from pathlib import Path

from taskloop.adapters import gitrepo
from taskloop.adapters.ident import config_dir
from taskloop.app.track.trail import now
from taskloop.contracts.env import Env
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Git
from taskloop.contracts.snapshots import SessionIndex
from taskloop.contracts.stores import SessionStore
from taskloop.domain import selfdescribe


def self_description(repo: str) -> str:
    """A cheap profile presence check; sessions need no profile parsing or tracker calls."""
    return selfdescribe.text() if repo and (Path(repo) / ".task-loop.json").is_file() else ""


def session_start(stdin_text: str, env: Env) -> None:
    try:
        d = json.loads(stdin_text or "{}")
        sid = d.get("session_id")
        if sid:
            SessionStore(ConfigDir(config_dir(env)), sid).write(SessionIndex(
                session=sid, transcript=d.get("transcript_path") or "", cwd=d.get("cwd") or "", source=d.get("source") or "", t=now()))
    except Exception:
        pass


SHIM = (
    "#!/bin/sh\n"
    "command -v uv >/dev/null 2>&1 || { echo 'tl: uv is required (https://docs.astral.sh/uv/)' >&2; exit 127; }\n"
    "exec uv run --quiet --script {tl} \"$@\"\n"
)


def version_key(name: str) -> tuple[int, ...]:
    """Numeric cache version, or () for a source checkout / unrelated directory."""
    parts = name.split(".")
    return tuple(int(p) for p in parts) if all(p.isascii() and p.isdecimal() for p in parts) else ()


def newest_install(plugin_root: Path) -> Path:
    """Choose among sibling cache versions; source checkouts run their own code."""
    if not version_key(plugin_root.name):
        return plugin_root
    return max((p for p in plugin_root.parent.iterdir() if version_key(p.name) and p.is_dir()),
               key=lambda p: version_key(p.name), default=plugin_root)


def readable_install(plugin_root: Path) -> Path | None:
    """Do not replace either launcher when the newest install is incomplete or unreadable."""
    try:
        newest = newest_install(plugin_root)
        for name in ("skills/task-loop/tl.py", "hooks/hook.py"):
            (newest / name).read_bytes()
        return newest
    except OSError:
        return None


def write_shim(plugin_root: Path, env: Env) -> None:
    """<config>/bin/tl: a stable path running the newest readable install through `uv run --script`."""
    install = readable_install(plugin_root)
    if install is None:
        return
    text = SHIM.replace("{tl}", shlex.quote(str(install / "skills" / "task-loop" / "tl.py")))
    with contextlib.suppress(OSError):
        put_launcher(config_dir(env) / "bin" / "tl", text)


def put_launcher(f: Path, text: str) -> None:
    """Write a launcher read-only, through a temp file and os.replace: an older install's write_text (it writes its own path
    unconditionally) fails on the read-only file and swallows the error, so a session on an old plugin cannot downgrade it."""
    if f.is_file() and f.read_text(encoding="utf-8") == text:
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f".{f.name}.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o555)
    tmp.replace(f)


# The client hooks tl's dir answers (git reads core.hooksPath for all of them); the dispatcher of each also runs the repo's own hook.
HOOK_NAMES = ("applypatch-msg", "pre-applypatch", "post-applypatch", "pre-commit", "pre-merge-commit", "prepare-commit-msg", "commit-msg",
              "post-commit", "pre-rebase", "post-checkout", "post-merge", "pre-push", "post-rewrite", "pre-auto-gc")
GIT_HOOK = (
    "#!/bin/sh\n"
    "# written by `tl hooks install`; plain python3, no uv. pre-push forwards stdin to `tl judge-push`; then the repo's own hook of this\n"
    "# name runs with the same arguments and stdin (hook/prepush.py), so git-lfs's and the repo's hooks are not skipped\n"
    "exec python3 {hook} githook {name} {tl} \"$@\"\n"
)


def write_hooks(plugin_root: Path, env: Env) -> list[Path]:
    """<config>/githooks/: one dispatcher per client hook name. It runs tl's logic (pre-push), then the repo's own hook of that name,
    found at run time, so a repo's changed hooks are followed without a rewrite. Every subprocess tl starts gets this folder as
    core.hooksPath (adapters/childenv.hooks_vars). Idempotent; a failure to write is silent (a session must start)."""
    install = readable_install(plugin_root)
    if install is None:
        return []
    root = config_dir(env)
    hook, tl = shlex.quote(str(install / "hooks" / "hook.py")), shlex.quote(str(root / "bin" / "tl"))
    out = []
    for name in HOOK_NAMES:
        text = GIT_HOOK.replace("{hook}", hook).replace("{tl}", tl).replace("{name}", name)
        f = ConfigDir(root).hooks_dir() / name
        try:
            put_launcher(f, text)
        except OSError:
            return []
        out.append(f)
    return out


def main_checkout(git: Git, cwd: str) -> str:
    """The repo the loop's files are keyed by: the main checkout of the work tree at `cwd` (a worktree or slot of it too), else cwd."""
    common = Path(git.common_dir(cwd) or ".")
    return str(common.parent) if common.name == ".git" else gitrepo.repo_root(cwd)


def repo_of(git: Git, data: dict[str, object]) -> str:
    cwd = str(data.get("cwd") or "")
    return main_checkout(git, cwd) if cwd and Path(cwd).is_dir() else ""
