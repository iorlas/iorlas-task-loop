"""Scenario 3: `tl` and the dashboard as real processes: ensure starts the server, it answers over HTTP, stop ends it."""
import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import support.paths

TL = Path(support.paths.ROOT) / "skills" / "task-loop" / "tl.py"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def tl(*args, timeout=300):
    cmd = ["uv", "run", "--quiet", "--script", str(TL), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.read().decode()


def test_given_no_dashboard_when_tl_ensures_it_then_it_answers_and_stop_ends_it(world, monkeypatch):
    # Given: a port of our own (the installed dashboard on 7878 is never touched) and nothing listening there
    port = free_port()
    monkeypatch.setenv("TASK_LOOP_DASH_PORT", str(port))
    monkeypatch.setenv("TASK_LOOP_DASH_BIND", "127.0.0.1")
    assert tl("dash", "status").returncode == 1
    pid = None
    try:
        # When: tl starts it
        ensured = tl("dash", "ensure")
        assert ensured.returncode == 0, ensured.stdout + ensured.stderr
        assert f"DASHBOARD http://127.0.0.1:{port}" in ensured.stdout
        # Then: it answers its version and its page, and tl status reports it
        status, body = get(f"http://127.0.0.1:{port}/api/version")
        info = json.loads(body)
        pid = info["pid"]
        assert status == 200 and pid != os.getpid()
        assert get(f"http://127.0.0.1:{port}/")[0] == 200
        assert tl("dash", "status").returncode == 0
    finally:
        # When: tl stops it, Then: it no longer answers and its process is gone
        tl("dash", "stop")
        if pid:
            end = time.time() + 20
            while time.time() < end and Path(f"/proc/{pid}").exists():
                time.sleep(0.2)
    assert tl("dash", "status").returncode == 1
    assert not (Path("/proc").is_dir() and Path(f"/proc/{pid}").exists())
