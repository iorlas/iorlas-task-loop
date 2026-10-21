"""post-checkout hook of the race test's repo: a checkout in a worktree whose engine lock names a live process must
come from that process (or a child of it). Appends a line per checkout to $FAKE_CHECKOUT_LOG; always exits 0, since a
post-checkout hook's exit is the checkout's."""

import json
import os
import subprocess
import time


def parent(pid):
    try:
        with open("/proc/%d/stat" % pid) as f:
            return int(f.read().rsplit(")", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        pass
    try:
        return int(subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True).stdout.strip())
    except (OSError, ValueError):
        return 0


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def main():
    cwd = os.path.realpath(os.getcwd())
    try:
        with open(os.path.join(cwd, ".task", "engine.lock"), encoding="utf-8") as f:
            lock = json.load(f)
    except (OSError, ValueError):
        lock = {}
    pid = lock.get("pid") if alive(lock.get("pid")) else None
    chain, p = [], os.getppid()
    while pid and p > 1 and len(chain) < 12:
        chain.append(p)
        p = parent(p)
    return {"t": time.time(), "cwd": cwd, "lock": pid, "by": lock.get("by"), "chain": chain,
            "ok": not pid or pid in chain}


try:
    rec = main()
except Exception as e:  # never fail the checkout; the test reads this as a bad line
    rec = {"t": time.time(), "cwd": os.getcwd(), "ok": False, "error": repr(e)}
with open(os.environ["FAKE_CHECKOUT_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(rec) + "\n")
