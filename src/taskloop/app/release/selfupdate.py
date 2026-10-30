"""A release runs origin/main's release code, not the code of the checkout it was launched from (that checkout lags: only the release
clone is reset to origin/main). When the clone's code differs, the launcher execs the clone's dev/release.py."""
import os
from collections.abc import Sequence
from pathlib import Path

from taskloop.adapters import applog, childenv
from taskloop.app.release.shell import Shell, say
from taskloop.contracts import env as penv
from taskloop.contracts.envvars import EnvVar

CODE = ("src", "dev/release.py")  # what a release runs: the engine package and the entry script


def code_ids(root: Path, sh: Shell) -> list[str]:
    """The tree ids of CODE at the HEAD of `root` ("" for one that is missing or not a git repo)."""
    return [sh.git(root, "rev-parse", "-q", "--verify", f"HEAD:{p}", check=False) for p in CODE]


def newer_release(tool_root: Path, where: Path, sh: Shell) -> Path | None:
    """The clone's dev/release.py when `where` (on origin/main) holds release code other than `tool_root`'s; None when they are the
    same, the clone has no such script, or this process is already the exec'd one. The marker is taken out of the environment here,
    so nothing the release starts (the suite, its release tests) inherits it."""
    script = where / "dev" / "release.py"
    if penv.take(EnvVar.TL_RELEASE_REEXEC) or not script.is_file() or code_ids(tool_root, sh) == code_ids(where, sh):
        return None
    return script


def exec_release(script: Path, argv: Sequence[str], repo: Path) -> None:
    """Replace this process with origin/main's release, same arguments, --repo made explicit (the default would be the clone). The caller
    holds no lock: the exec'd release takes it."""
    args = list(argv) + ([] if any(a == "--repo" or a.startswith("--repo=") for a in argv) else ["--repo", str(repo)])
    say(f"this checkout's release code is not origin/main's; running {script}")
    penv.export(EnvVar.TL_RELEASE_REEXEC, "1")
    applog.close_all()
    cmd = [*childenv.script_argv(script), *args]
    os.execv(cmd[0], cmd)
