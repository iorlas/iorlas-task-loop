"""The delegate tests import their helpers (hermetic, routing_support, run_support) by flat name: this folder is on sys.path for them.
Every test runs in a home of its own (hermetic.home): HOME, XDG, CODEX_HOME and DELEGATE_CONFIG_DIR point into a fresh temp dir."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import hermetic  # noqa: E402

ENV = ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "CODEX_HOME", "DELEGATE_CONFIG_DIR", "TMPDIR")


@pytest.fixture(autouse=True)
def own_home():
    saved = {k: os.environ.get(k) for k in ENV}
    d = tempfile.mkdtemp(prefix="t-", dir=hermetic.ROOT)
    hermetic.home(d)
    try:
        yield
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        shutil.rmtree(d, ignore_errors=True)
