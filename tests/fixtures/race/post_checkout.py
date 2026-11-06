"""post-checkout hook of the race test's repo: a checkout in a worktree whose engine lock names a live process must
come from that process (or a child of it). Appends a line per checkout to $FAKE_CHECKOUT_LOG; always exits 0, since a
post-checkout hook's exit is the checkout's."""

import hashlib
import json
import os
import sqlite3
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


def read_lock(cwd):
    """The engine lock of the worktree `cwd` as a dict: its `lease` row `run` `engine:<folder>-<8 hex of sha1 of its real path>` in
    <config>/factory.db, else an older tl's locks/engine-<key>.lock file; {} when there is none."""
    real = os.path.realpath(cwd)
    key = f"{os.path.basename(real)}-{hashlib.sha1(real.encode()).hexdigest()[:8]}"
    base = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"), "task-loop")
    try:
        con = sqlite3.connect("file:%s?mode=ro" % os.path.join(base, "factory.db"), uri=True)
        try:
            row = con.execute("SELECT body FROM lease WHERE kind='run' AND name=?", ("engine:" + key,)).fetchone()
        finally:
            con.close()
        if row:
            return json.loads(row[0])
    except (sqlite3.Error, ValueError):
        pass
    try:
        with open(os.path.join(base, "locks", f"engine-{key}.lock"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def main():
    cwd = os.path.realpath(os.getcwd())
    lock = read_lock(cwd)
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
