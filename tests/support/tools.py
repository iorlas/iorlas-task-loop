"""Tools a test needs for real. Each is resolved ONCE, at import, before any test changes HOME: a mise shim fails in a fresh
directory or under a temp HOME, so the real binary behind it is found (`mise which`, else mise's newest install) and its
directory is put on PATH by `on_path`. No binary at all means the test skips; a shim that merely cannot run here does not."""
import contextlib
import glob
import os
import pwd
import shutil
import subprocess
from unittest import mock


def _runs(path):
    try:
        return subprocess.run([path, "--version"], capture_output=True, timeout=20, cwd="/", check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _resolve(tool):
    """The real executable of `tool`, or None. A path under .../mise/shims is followed to the install it stands for."""
    found = shutil.which(tool)
    if found and os.sep + os.path.join("mise", "shims") + os.sep not in found and _runs(found):
        return found
    candidates = []
    if shutil.which("mise"):
        try:
            r = subprocess.run(["mise", "which", tool], capture_output=True, text=True, timeout=20, cwd="/", check=False)
            candidates.append(r.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    home = pwd.getpwuid(os.getuid()).pw_dir  # the account's, whatever $HOME says
    for data in filter(None, (os.environ.get("MISE_DATA_DIR"), os.path.join(home, ".local", "share", "mise"))):
        for layout in (("bin", tool), (tool,)):  # node keeps bin/, just sits in the version folder
            candidates += sorted(glob.glob(os.path.join(data, "installs", tool, "[0-9]*", *layout)), reverse=True)
    return next((c for c in candidates if c and os.path.isfile(c) and _runs(c)), None)


REAL = {t: _resolve(t) for t in ("just", "node")}


def real(tool):
    """Absolute path of the real `tool` found at import, or None."""
    return REAL.get(tool) or _resolve(tool)


def need(test, tool):
    """Skip the running test only when no real `tool` exists on this machine at all."""
    if not real(tool):
        test.skipTest(f"no real `{tool}` binary on this machine")


def on_path(tool):
    """Context: the real `tool`'s directory first on PATH, so code that runs the bare name through PATH runs the real one."""
    path = real(tool)
    if not path:
        return contextlib.nullcontext()
    return mock.patch.dict(os.environ, {"PATH": os.path.dirname(path) + os.pathsep + os.environ.get("PATH", "")})
