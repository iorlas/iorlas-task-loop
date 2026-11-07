"""Shell command helpers preserve arguments and isolate version manager shims."""
import os
import shlex
import sys

from tltestkit.shellkit import pyc, shq, without_shims


def test_pyc_round_trips():
    code = "print('hello world')"
    args = ("two words", "quote'word", "")
    assert shlex.split(pyc(code, *args)) == [sys.executable, "-c", code, *args]


def test_shq_quotes_space():
    assert shlex.split(shq("two words")) == ["two words"]


def test_without_shims(monkeypatch):
    original = os.pathsep.join(("/tools/bin", "/tools/shims", "/usr/bin"))
    monkeypatch.setenv("PATH", original)

    @without_shims
    def path_inside():
        return os.environ["PATH"]

    assert path_inside() == os.pathsep.join(("/tools/bin", "/usr/bin"))
    assert os.environ["PATH"] == original
