"""The SessionStart hook: index the session id -> its transcript path. Must never fail the session."""
import contextlib
import os
import shlex
from pathlib import Path

from taskloop.adapters import gitrepo
from taskloop.adapters.ident import config_dir
from taskloop.contracts.env import Env
from taskloop.contracts.paths import ConfigDir, default_root
from taskloop.contracts.ports import Git
from taskloop.domain import selfdescribe


def self_description(repo: str) -> str:
    """A cheap profile presence check; sessions need no profile parsing or tracker calls."""
    return selfdescribe.text() if repo and (Path(repo) / ".task-loop.json").is_file() else ""


SHIM = (
    "#!/bin/sh\n"
    "command -v uv >/dev/null 2>&1 || { echo 'tl: uv is required (https://docs.astral.sh/uv/)' >&2; exit 127; }\n"
    "exec uv run --quiet --script {tl} \"$@\"\n"
)
# The shim of a cache install: the newest installed version is picked on every call (pure sh, a glob and integer arithmetic, no
# subprocess), so a release or a pruned cache dir needs no rewrite; the path the writer saw is the fallback when none is found.
RESOLVING_MARK = "# newest installed version, resolved at run time"
RESOLVING_SHIM = (
    "#!/bin/sh\n"
    + RESOLVING_MARK + "\n"
    "command -v uv >/dev/null 2>&1 || { echo 'tl: uv is required (https://docs.astral.sh/uv/)' >&2; exit 127; }\n"
    "tl={tl}\n"
    "best=0\n"
    "pick() {\n"
    "  for p in {cache}/*/skills/task-loop/tl.py; do\n"
    "    [ -f \"$p\" ] || continue\n"
    "    v=${p%/skills/task-loop/tl.py}; v=${v##*/}\n"
    "    case $v in ''|*[!0-9.]*|.*|*.|*..*|0[0-9]*|*.0[0-9]*) continue;; esac\n"
    "    IFS=.; set -- $v; unset IFS\n"
    "    [ $# -eq 3 ] || continue\n"
    "    k=$(( $1 * 10000000000 + $2 * 100000 + $3 ))\n"
    "    [ \"$k\" -gt \"$best\" ] && { best=$k; tl=$p; }\n"
    "  done\n"
    "}\n"
    "pick\n"
    "exec uv run --quiet --script \"$tl\" \"$@\"\n"
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
    tl = shlex.quote(str(install / "skills" / "task-loop" / "tl.py"))
    text = (RESOLVING_SHIM.replace("{cache}", shlex.quote(str(install.parent))) if version_key(install.name) else SHIM).replace("{tl}", tl)
    with contextlib.suppress(OSError):
        put_launcher(config_dir(env) / "bin" / "tl", text)


def path_link(env: Env) -> Path:
    """~/.local/bin/tl, under the HOME of `env` (a test passes its own, so none ever touches the real one)."""
    return Path(env.get("HOME") or Path.home()) / ".local" / "bin" / "tl"


def link_state(env: Env) -> str:
    """The PATH link: 'ours' (a symlink to the shim), 'foreign' (anything else is there), 'missing', or 'windows' (no link there)."""
    if os.name == "nt":
        return "windows"
    link, shim = path_link(env), default_root(env) / "bin" / "tl"  # not config_dir: it makes the folder, and this only looks
    if link.is_symlink():
        return "ours" if os.readlink(link) == str(shim) or os.path.realpath(link) == os.path.realpath(shim) else "foreign"
    return "foreign" if link.exists() else "missing"


def ensure_path_link(env: Env) -> None:
    """Link ~/.local/bin/tl to the shim, so `tl` works from any shell. Never replaces a different `tl`, never makes ~/.local (a machine
    without it does not use it), idempotent, and never raises: a session must start."""
    with contextlib.suppress(OSError):
        link = path_link(env)
        if link_state(env) == "missing" and link.parent.parent.is_dir():
            link.parent.mkdir(exist_ok=True)
            link.symlink_to(config_dir(env) / "bin" / "tl")


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
    "# written by tl; plain python3, no uv. pre-push forwards stdin to `tl judge-push`; then the repo's own hook of this\n"
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


def ensure_machine(plugin_root: Path, env: Env) -> None:
    """The per-user setup, idempotent: the config folder, the shim, the PATH link, the git hooks. `tl setup --apply` and SessionStart
    both run exactly this."""
    config_dir(env).mkdir(parents=True, exist_ok=True)
    write_shim(plugin_root, env)
    ensure_path_link(env)
    write_hooks(plugin_root, env)


ENGINE_VERBS = frozenset({"loop", "run-task", "land-stack"})


def heal(verb: str, plugin_root: Path, env: Env) -> None:
    """The engine verbs make sure the hooks dir exists and is current (a file compare when it is): a missing dir would turn the delivery
    judge silently off. Any other verb leaves it alone."""
    if verb in ENGINE_VERBS:
        write_hooks(plugin_root, env)


def main_checkout(git: Git, cwd: str) -> str:
    """The repo the loop's files are keyed by: the main checkout of the work tree at `cwd` (a worktree or slot of it too), else cwd."""
    common = Path(git.common_dir(cwd) or ".")
    return str(common.parent) if common.name == ".git" else gitrepo.repo_root(cwd)


def repo_of(git: Git, data: dict[str, object]) -> str:
    cwd = str(data.get("cwd") or "")
    return main_checkout(git, cwd) if cwd and Path(cwd).is_dir() else ""
