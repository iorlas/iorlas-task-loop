"""What each test touches: a pytest plugin loaded only by an explicit `-p testtouch` (PYTHONPATH=dev), never by default.

`TL_TEST_TOUCH=<file.json> PYTHONPATH=dev pytest -p testtouch ...` counts, per test (setup + call + teardown) and per phase, the calls the
test makes to: open() for write or read, mkdir / unlink / rename / rmdir, sqlite3.connect, subprocess spawns (git apart), os.fork, sockets,
and time.sleep (count and seconds). Writes and reads are split by where the path is: the temp dir, the repo checkout, anywhere else.
Python-level patches only: a C extension's own file access and a child's work are not seen. Fakes that replace subprocess for a test
(tests/support/procsim.py) shadow the counters, which is the point: a faked spawn is not a spawn. Rewritten every 25 tests."""
import builtins
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

ROOT = str(Path(__file__).resolve().parent.parent)
TMP = os.path.realpath(tempfile.gettempdir())
_REAL_OPEN = builtins.open
_ROWS: dict[str, dict[str, float]] = {}
_NOW: list = [None, None]  # [row, phase]
_WRITE = set("wax+")


def _where(path) -> str:
    try:
        if not os.fspath(path):
            return "other"
        text = os.path.realpath(os.fspath(path))
    except (TypeError, ValueError):
        return "other"
    if text.startswith(TMP) or text.startswith("/tmp") or text.startswith("/var/folders") or text.startswith("/private/tmp"):
        return "tmp"
    return "repo" if text.startswith(ROOT) else "other"


def _bump(key: str, n: float = 1, path=None) -> None:
    row, phase = _NOW
    if path is not None and row is not None and key.endswith("_repo") and "ex_" + key not in row:
        row["ex_" + key] = os.fspath(path)
    if row is not None:
        row[key] = row.get(key, 0) + n
        row[f"{phase}:{key}"] = row.get(f"{phase}:{key}", 0) + n


def _install() -> None:
    def op_open(file, mode="r", *a, **k):
        if isinstance(file, int):
            return _REAL_OPEN(file, mode, *a, **k)
        _bump(("write_" if _WRITE & set(str(mode)) else "read_") + _where(file), 1, file)
        return _REAL_OPEN(file, mode, *a, **k)

    builtins.open = op_open
    for name in ("mkdir", "unlink", "rmdir", "rename", "replace", "symlink"):
        real = getattr(os, name)

        def wrap(*a, _real=real, _name=name, **k):
            where = "tmp" if k.get("dir_fd") is not None else _where(a[0] if a else k.get("path", ""))  # shutil.rmtree works by dir_fd
            _bump("write_" + where, 1, a[0] if a else "")
            return _real(*a, **k)

        setattr(os, name, wrap)
    real_connect = sqlite3.connect
    sqlite3.connect = lambda database, *a, **k: (_bump("sqlite_" + _where(database)), real_connect(database, *a, **k))[1]
    real_init = subprocess.Popen.__init__

    def popen_init(self, args, *a, **k):
        first = args if isinstance(args, str) else (args[0] if args else "")
        _bump("git_spawn" if os.path.basename(str(first)) == "git" else "proc_spawn")
        real_init(self, args, *a, **k)

    subprocess.Popen.__init__ = popen_init
    real_fork = os.fork
    os.fork = lambda: (_bump("fork"), real_fork())[1]
    for name in ("connect", "bind"):
        real = getattr(socket.socket, name)
        setattr(socket.socket, name, lambda self, *a, _real=real, _name=name: (_bump("socket_" + _name), _real(self, *a))[1])
    real_sleep = time.sleep

    def sleep(seconds):
        _bump("sleeps")
        _bump("sleep_s", float(seconds))
        return real_sleep(seconds)

    time.sleep = sleep


def pytest_configure(config):
    if os.environ.get("TL_TEST_TOUCH"):
        _install()


def _phase(item, phase):
    row = _ROWS.setdefault(item.nodeid, {})
    _NOW[:] = [row, phase]
    try:
        return (yield)
    finally:
        _NOW[:] = [None, None]


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    return (yield from _phase(item, "setup"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    return (yield from _phase(item, "call"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    return (yield from _phase(item, "teardown"))


def _dump() -> None:
    path = os.environ.get("TL_TEST_TOUCH")
    if path:
        with _REAL_OPEN(path + ".part", "w", encoding="utf-8") as out:
            json.dump(_ROWS, out)
        os.replace(path + ".part", path)


def pytest_runtest_logfinish(nodeid, location):
    if len(_ROWS) % 25 == 0:
        _dump()


def pytest_sessionfinish(session):
    _dump()
