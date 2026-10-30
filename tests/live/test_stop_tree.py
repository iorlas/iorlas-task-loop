"""Scenario 4: a stop kills a real worker process tree: stream_proc.run (what runs every worker and check) is told to stop while a shell
worker has children in its own group and in sessions of their own; afterwards no process of the tree is alive."""
import sys
import threading
import time

import stream_proc

from taskloop.adapters import procs

WORKER = r"""
import os, subprocess, sys, time
sleeper = ["sh", "-c", "exec sleep 300"]
stubborn = ["sh", "-c", "trap '' TERM; exec sleep 300"]
kids = [subprocess.Popen(sleeper), subprocess.Popen(sleeper, start_new_session=True),
        subprocess.Popen(stubborn), subprocess.Popen(stubborn, start_new_session=True)]
time.sleep(0.5)
print("PIDS", *[k.pid for k in kids], flush=True)
time.sleep(300)
"""


def alive(pid):
    state = procs.proc_start(pid)
    return state is not None and procs.alive(pid, state)


def test_given_a_worker_tree_when_the_run_is_stopped_then_every_process_in_it_dies():
    # Given: a worker with four children (two in its group, two in own sessions; two ignore SIGTERM), all running
    lines, stop = [], threading.Event()
    done = {}
    argv = [sys.executable, "-c", WORKER]
    t = threading.Thread(target=lambda: done.update(r=stream_proc.run(argv, on_stdout=lines.append, stop=stop, grace=1.0)))
    t.start()
    end = time.time() + 30
    while time.time() < end and not any(x.startswith("PIDS") for x in lines):
        time.sleep(0.1)
    kids = [int(x) for x in next(x for x in lines if x.startswith("PIDS")).split()[1:]]
    assert len(kids) == 4 and all(alive(p) for p in kids)
    # When: the stop flag is set (what `tl stop --now` and a wall limit do to a run)
    stop.set()
    t.join(60)
    # Then: the run ended as stopped and no process of the tree is left
    assert not t.is_alive() and done["r"].timed_out == "stopped" and not done["r"].survivors
    deadline = time.time() + 30
    while time.time() < deadline and any(alive(p) for p in kids):
        time.sleep(0.1)
    assert [p for p in kids if alive(p)] == []
