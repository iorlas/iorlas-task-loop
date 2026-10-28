"""The SessionStart hook: index the session id -> its transcript path. Must never fail the session."""
import json
import shlex
from pathlib import Path

from taskloop.adapters import gitrepo
from taskloop.adapters.ident import config_dir
from taskloop.app.track.trail import now
from taskloop.contracts.paths import ConfigDir


def session_start(stdin_text: str) -> None:
    try:
        d = json.loads(stdin_text or "{}")
        sid = d.get("session_id")
        if sid:
            f = ConfigDir(config_dir()).session(sid)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"session": sid, "transcript": d.get("transcript_path"), "cwd": d.get("cwd"),
                                     "source": d.get("source"), "t": now()}), encoding="utf-8")
    except Exception:
        pass


SHIM = "#!/bin/sh\nexec python3 {tl} \"$@\"\n"


def write_shim(plugin_root: Path) -> None:
    """<config>/bin/tl: a path that does not change with the plugin version, running this install's tl.py."""
    f = config_dir() / "bin" / "tl"
    text = SHIM.format(tl=shlex.quote(str(plugin_root / "skills" / "task-loop" / "tl.py")))
    try:
        if f.is_file() and f.read_text(encoding="utf-8") == text:
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        f.chmod(0o755)
    except OSError:
        pass


def main_checkout(cwd: str) -> str:
    """The repo the loop's files are keyed by: the main checkout of the work tree at `cwd` (a worktree or slot of it too), else cwd."""
    common = Path(gitrepo.git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd) or ".")
    return str(common.parent) if common.name == ".git" else gitrepo.repo_root(cwd)


def repo_of(data: dict[str, object]) -> str:
    cwd = str(data.get("cwd") or "")
    return main_checkout(cwd) if cwd and Path(cwd).is_dir() else ""
