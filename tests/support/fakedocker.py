"""A `docker` on PATH for tests: records each call, and `run` executes the command locally in a sandbox dir that stands for the
container's disk (TMPDIR), so a check's result is real. No daemon needed."""
import json
import os
import stat
from pathlib import Path

SHIM = r'''#!{py}
import json, os, signal, subprocess, sys
root = {root!r}
args = sys.argv[1:]
with open(root + "/calls.jsonl", "a") as f:
    f.write(json.dumps(args) + "\n")
cmd = args[0] if args else ""
if cmd == "info":
    sys.exit(1 if os.path.exists(root + "/down") else 0)
if cmd in ("image", "build"):
    sys.exit(0)
if cmd == "kill":
    try:
        os.kill(int(open(root + "/" + args[1] + ".pid").read()), signal.SIGKILL)
    except (OSError, ValueError):
        pass
    sys.exit(0)
if cmd == "rm":
    sys.exit(0)
if cmd == "cp":
    name = args[1].split(":")[0]
    sys.exit(subprocess.run(["tar", "-c", "-C", root + "/" + name + "/tl-art", "."]).returncode)
if cmd == "run":
    env, name, i = dict(os.environ), "", 1
    while args[i].startswith("-"):
        if args[i] in ("--name", "-w", "-e"):
            if args[i] == "--name":
                name = args[i + 1]
            elif args[i] == "-e":
                k, _, v = args[i + 1].partition("=")
                env[k] = v
            i += 1
        i += 1
    box = root + "/" + name
    os.makedirs(box, exist_ok=True)
    env["TMPDIR"] = box
    open(root + "/" + name + ".pid", "w").write(str(os.getpid()))
    os.execvpe(args[i + 1], args[i + 1:], env)
sys.exit(2)
'''


class FakeDocker:
    def __init__(self, root, py):
        self.root = Path(root)
        self.bin = self.root / "bin"
        self.bin.mkdir(parents=True)
        shim = self.bin / "docker"
        shim.write_text(SHIM.format(py=py, root=str(self.root)))
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR)

    @property
    def path(self):
        return str(self.bin) + os.pathsep + os.environ["PATH"]

    def calls(self):
        f = self.root / "calls.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def verbs(self):
        return [c[0] for c in self.calls()]

    def down(self):
        (self.root / "down").write_text("")
