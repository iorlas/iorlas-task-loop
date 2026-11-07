"""Shell helpers for tests: one-line commands, quoting, platform skips. No Engine, no host."""
import functools
import os
import shlex
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from tltestkit.checked import run_checked


def sh(*a, cwd):
    run_checked(list(a), cwd)


POSIX_CHECK = pytest.mark.skipif(os.name == "nt", reason="the check is bash (operators, $VAR, rm, test, grep, sleep, /dev/null); "
                                              "on Windows the engine runs checks through cmd.exe")


ENGINE_BASH = pytest.mark.skipif(os.name == "nt",
                                 reason="the engine's own conflict-marker check (`! git grep ...`) is bash; cmd.exe cannot parse it")


def without_shims(fn):
    """A tool the machine's version manager shims but has not installed (mise: `ruff is not a valid shim`) exits 1, not 127:
    the test means a tool that is missing, so the shim directories leave PATH."""
    @functools.wraps(fn)
    def run(*a, **kw):
        keep = os.pathsep.join(d for d in os.environ.get("PATH", "").split(os.pathsep) if "shims" not in d)
        with mock.patch.dict(os.environ, {"PATH": keep}):
            return fn(*a, **kw)
    return run


EXIT_127 = pytest.mark.skipif(os.name == "nt", reason="the engine reads a missing tool as bash's exit 127; cmd.exe reports it as exit 1")


NO_FCNTL = pytest.mark.skipif(os.name == "nt", reason="the lock is fcntl; tl has none on Windows (documented no-op)")


def shq(text):
    """One shell word for the engine's check runner: bash quoting on POSIX, CreateProcess quoting for cmd.exe on Windows."""
    return shlex.quote(text) if os.name != "nt" else subprocess.list2cmdline([text])


def shown(p):
    """A path as git and the engine print it: forward slashes and long names on Windows."""
    return Path(p).resolve().as_posix() if os.name == "nt" else str(p)


PY = f'"{sys.executable}"'


def pyc(code, *args):
    """A check as its one-line text: this interpreter running `code`, then the arguments."""
    return shlex.join([sys.executable, "-c", code, *args])
