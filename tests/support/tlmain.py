"""`tl.py` run in this process: what `python3 tl.py ARGS` shows, with no interpreter start."""
import contextlib
import io
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401  (ROOT/src on sys.path)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import tl  # noqa: E402


def tl_main(*args, cwd, env=None):
    """tl.main(args) in this process, from `cwd`: -> (exit code, stdout, stderr). A SystemExit carries its code, a message is
    printed to stderr and exits 1, as the interpreter does for a script."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.chdir(cwd), mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = tl.main(list(args))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 0 if e.code is None else 1
            if isinstance(e.code, str):
                print(e.code, file=sys.stderr)
    return subprocess.CompletedProcess(list(args), code, out.getvalue(), err.getvalue())
