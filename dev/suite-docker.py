#!/usr/bin/env python3
"""The land gate in a Linux container: clone this checkout's HEAD onto the container's own disk, run dev/suite.py there.

    python3 dev/suite-docker.py [--repo DIR] [--image IMAGE]      exit code = the suite's

Why a container: the Mac's endpoint scanner taxes every file close, first read and process start; the container's own
disk has none of that. The code goes in by `git clone`, never a bind mount (a bind mount is as slow as the Mac).
Uncommitted changes to tracked files (the version bump of a release) are applied on top of the clone.
Image: --image, else $TASK_LOOP_SUITE_IMAGE, else task-loop-suite:<hash of the Dockerfile>, built from dev/Dockerfile.suite when missing.
When docker is not reachable: one warning line, then the suite on the host. Python 3, standard library only.
"""
import argparse
import contextlib
import hashlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE.parent / "skills" / "task-loop" / "_vendor"))  # the vendored shelf packages (dev/vendor.py)
import stream_proc  # noqa: E402

_DOCKERFILE_SHA = hashlib.sha1((HERE / "Dockerfile.suite").read_bytes()).hexdigest()[:10]
DEFAULT_IMAGE = "task-loop-suite:" + _DOCKERFILE_SHA  # a new Dockerfile is a new image
SUITE_WALL_S = 3 * 3600.0  # a hang guard for the whole host suite; each shard has its own, shorter, limit
INSIDE = ("git clone -q /src.git /w && cd /w && git checkout -q \"$SHA\" && cat > /tmp/p"
          " && { [ ! -s /tmp/p ] || git apply /tmp/p; } && python3 dev/suite.py")


def docker_ok():
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_image(image):
    if subprocess.run(["docker", "image", "inspect", image], capture_output=True, check=False).returncode == 0:
        return True
    if image != DEFAULT_IMAGE:
        print(f"suite-docker: image {image} not found", file=sys.stderr)
        return False
    print(f"suite-docker: building {image}", flush=True)
    return subprocess.run(["docker", "build", "-q", "-f", str(HERE / "Dockerfile.suite"), "-t", image, str(HERE)],
                          stdout=subprocess.DEVNULL, check=False).returncode == 0


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def host_suite(repo, why):
    print(f"suite-docker: WARNING {why}; running the suite on the host", file=sys.stderr, flush=True)
    old = signal.signal(signal.SIGTERM, lambda signum, _frame: sys.exit(128 + signum))  # unwinds into stream_proc.run, which stops the tree
    try:
        res = stream_proc.run([sys.executable, str(HERE / "suite.py"), "--repo", str(repo)],
                              on_stdout=lambda t: print(t, end="", flush=True),
                              on_stderr=lambda t: print(t, end="", file=sys.stderr, flush=True), timeout=SUITE_WALL_S)
    finally:
        signal.signal(signal.SIGTERM, old)
    return res.returncode if res.returncode is not None else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="suite-docker.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=str(HERE.parent), help="the checkout whose HEAD runs (default: this one)")
    ap.add_argument("--image", default=os.environ.get("TASK_LOOP_SUITE_IMAGE", DEFAULT_IMAGE))
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    if not docker_ok():
        return host_suite(repo, "docker is not reachable")
    if not ensure_image(args.image):
        return host_suite(repo, "the suite image is not available")
    sha = git(repo, "rev-parse", "HEAD").decode().strip()
    common = Path(os.fsdecode(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")).strip())
    patch = git(repo, "diff", "HEAD", "--binary")
    name = f"tl-suite-{os.getpid():d}-{int(time.time()):d}"
    inside = os.environ.get("TASK_LOOP_SUITE_INSIDE") or INSIDE  # the override is for the wrapper's own test
    cmd = ["docker", "run", "--rm", "--init", "-i", "--name", name, "-w", "/", "-e", "SHA=" + sha, "-v", f"{common}:/src.git:ro",
           args.image, "sh", "-c", inside]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def stop(signum, _frame):
        # killing the `docker run` client leaves the container running in the VM: kill it by name
        subprocess.run(["docker", "kill", name], capture_output=True, check=False)
        stream_proc.stop_tree(p, grace=10.0)
        sys.exit(128 + signum)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with contextlib.suppress(BrokenPipeError):
        p.communicate(patch)
    return p.wait()


if __name__ == "__main__":
    sys.exit(main())
