"""The effects ratchet counts syntax in kernel source, without resolving bindings."""
import ast

import pytest

from rules import effects_ratchet

KERNEL_FILE = "packages/kernel/src/tlkernel/example.py"


@pytest.mark.parametrize(("source", "expected"), [
    ("import sqlite3", {"sqlite": 1}),
    ("from sqlite3 import connect, Row", {"sqlite": 1}),
    ("import sqlite3 as db", {"sqlite": 1}),
    ("import stream_proc, subprocess, signal", {"process": 3}),
    ("from stream_proc import run", {"process": 1}),
    ("from subprocess import run\nfrom signal import SIGTERM", {"process": 2}),
    ("import shutil, tempfile, fcntl", {"files": 3}),
    ("from shutil import copy\nfrom tempfile import mkdtemp\nfrom fcntl import flock", {"files": 3}),
    ("import socket, urllib.request, http.client", {"net": 3}),
    ("from socket import socket\nfrom urllib.request import urlopen\nfrom http import client", {"net": 3}),
    ("import threading\nfrom threading import Thread", {"threads": 2}),
    ("os.replace('a', 'b')\nos.rename('a', 'b')\nos.remove('a')", {"files": 3}),
    ("'a'.replace('a', 'b')\ntext.replace('a', 'b')\nthing.remove('a')", {}),
    ("def open(): pass\nopen()", {"files": 1}),
    ("# import sqlite3\ntext = 'open()'\nimport pathlib\nfrom . import signal", {}),
    ("import sqlite3, threading\npath.touch()", {"sqlite": 1, "threads": 1, "files": 1}),
])
def test_effect_sites(source, expected):
    assert effects_ratchet.file_counts(KERNEL_FILE, ast.parse(source)) == expected


@pytest.mark.parametrize("name", sorted(effects_ratchet.FILE_CALLS))
@pytest.mark.parametrize("receiver", ["", "path."])
def test_named_file_calls(name, receiver):
    assert effects_ratchet.file_counts(KERNEL_FILE, ast.parse(f"{receiver}{name}()")) == {"files": 1}


@pytest.mark.parametrize("path", [
    "src/taskloop/example.py", "packages/other/src/tlkernel/example.py",
    "packages/kernel/tests/example.py", "packages/kernel/src/tlkernel_other/example.py",
    "packages/kernel/src/tlkernel/testing/helper.py", "packages/kernel/src/tlkernel/example.txt",
])
def test_other_paths_are_excluded(path):
    assert effects_ratchet.file_counts(path, ast.parse("import sqlite3")) == {}
