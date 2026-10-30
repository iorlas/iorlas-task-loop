#!/usr/bin/env python3
"""One check in a container, run as a child of the engine's shell (the engine's stop reaches it as SIGTERM).

    container_run.py --image I --name N --cwd REL [--art DIR] [--env K=V]... -- ARGV...    exit code = the check's

The worktree's tracked and untracked non-ignored files go in as a tar on stdin of `docker run -i` and are unpacked on the
container's own disk (never a bind mount); the check runs there; only its output, its exit code and the files it wrote under
$TL_ARTIFACTS come back (`docker cp`, unpacked into --art). A stop kills the container by its name. Standard library only."""
import argparse
import io
import os
import signal
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import IO, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/: a script run by path finds taskloop (which adds _vendor)
from taskloop.adapters import procs

INSIDE = ('t=${TMPDIR:-/tmp}; rm -rf "$t/tl-w" "$t/tl-art"; mkdir -p "$t/tl-w" "$t/tl-art" && tar -x -C "$t/tl-w"'
          ' && cd "$t/tl-w/$TL_BOX_CWD" && export TL_ARTIFACTS="$t/tl-art" && exec "$@"')  # the image must not set TMPDIR
ART_IN_BOX = "/tmp/tl-art"


def docker(*args: str, **kw: Any) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["docker", *args], capture_output=True, check=False, **kw)


def files(root: str) -> list[str]:
    """The tracked and the untracked non-ignored files of the worktree that still exist."""
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=root, capture_output=True, check=True).stdout
    return [os.fsdecode(p) for p in out.split(b"\0") if p and os.path.lexists(os.path.join(root, os.fsdecode(p)))]


def send(stream: IO[bytes], root: str) -> None:
    with tarfile.open(fileobj=stream, mode="w|") as tar:
        for rel in files(root):
            tar.add(os.path.join(root, rel), arcname=rel, recursive=False)


def fetch(name: str, art: str) -> None:
    """$TL_ARTIFACTS of the container, unpacked into the host's artifacts folder (nothing, when it has none)."""
    got = docker("cp", f"{name}:{ART_IN_BOX}/.", "-")
    try:
        with tarfile.open(fileobj=io.BytesIO(got.stdout), mode="r") as tar:
            tar.extractall(art, filter="data")
    except (tarfile.TarError, OSError):
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="container_run.py")
    ap.add_argument("--image", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--cwd", default="")
    ap.add_argument("--art", default="")
    ap.add_argument("--env", action="append", default=[])
    ap.add_argument("cmd", nargs="+")
    args = ap.parse_args(argv)
    cmd = ["docker", "run", "--init", "-i", "--name", args.name, "-w", "/", "-e", "TL_BOX_CWD=" + args.cwd]
    for kv in args.env:
        cmd += ["-e", kv]
    docker("rm", "-f", args.name)  # one left by a run that was SIGKILLed would refuse the name
    p = procs.spawn([*cmd, args.image, "sh", "-c", INSIDE, "sh", *args.cmd], stdin=subprocess.PIPE)

    def stop(signum: int, _frame: Any) -> None:
        docker("kill", args.name)  # killing the `docker run` client leaves the container running: kill it by its name
        sys.exit(128 + signum)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        try:
            if p.stdin:
                send(p.stdin, os.getcwd())
            if p.stdin:
                p.stdin.close()
        except BrokenPipeError:
            pass
        return p.wait()
    finally:
        if p.poll() is None:
            procs.stop_tree(p, grace=5.0)
        if args.art:
            fetch(args.name, args.art)
        docker("rm", "-f", args.name)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
