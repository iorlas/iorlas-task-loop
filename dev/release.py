#!/usr/bin/env python3
"""Release the plugin: one release at a time, the version from origin, the suite green, the marketplace bumped.

    python3 dev/release.py "message" [--bead ID --reason R] [--from-branch B] [--minor]
                           [--repo DIR] [--marketplace DIR]

Takes an OS lock (~/.config/task-loop/locks/release-*.lock): a second release waits in line and prints who holds it.
Then, in the repo's main checkout (on main, clean, or refused): fetch, fast-forward to origin/main, rebase B's commits
onto origin/main when given, leaving B and its worktrees unchanged (refusing if B omits unpublished main commits),
bump the patch version of origin/main's
.claude-plugin/plugin.json (--minor: the minor), run the full suite (red aborts and puts main back), commit only
plugin.json as "<version>: <message>", push under the land lock, so no loop lands in between. When origin/main moved
since the bump (a land during the suite) it drops the bump, rebases, takes the next version and runs the suite again
first, still under the lock; a push refused all the same gets one more such round. Then close the bead, bump the plugin's entry in the marketplace
checkout, push it, tag both pushed commits (`v<version>` in the repo, `iorlas-task-loop-v<version>` in the marketplace; the
tag is pushed only after its branch push succeeded), `claude plugin marketplace update` and `claude plugin update`. The
installed cache dir for the new version must exist afterwards: if not, the install runs once more, then the release
exits non-zero naming the failing command. Every release, green or red, writes ~/.config/task-loop/releases/last.json
and a failed one also comments on --bead and ends with a one-line "release FAILED" summary. Nothing is ever deleted: a
plugin cache dir a live engine runs from stays.

Run it from any worktree; it acts on the main checkout. Python 3.8+, standard library only.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "task-loop"))
import tl  # noqa: E402

PLUGIN = ".claude-plugin/plugin.json"
MARKET = ".claude-plugin/marketplace.json"
NAME = "iorlas-task-loop"
MARKETPLACE = "iorlas-marketplace"
TRAILER = "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


class Abort(Exception):
    """A refusal or failure that stops the release. `log`: the saved full suite output; `tests`: the failing test ids;
    `version`: set once main was pushed (the failure came after, e.g. the install)."""

    def __init__(self, msg, log="", tests=(), version=""):
        super().__init__(msg)
        self.log, self.tests, self.version = str(log or ""), list(tests), version


def run(cmd, cwd, check=True):
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        raise Abort("%s failed in %s:\n%s" % (" ".join(cmd), cwd, (r.stdout + r.stderr).strip()[-2000:]))
    return r


def git(cwd, *a, check=True):
    return run(["git"] + list(a), cwd, check).stdout.strip()


def fetch(cwd):
    """A fetch into the repo, again while it loses a ref lock to a loop's fetch at the same moment (tl.fetch)."""
    r = tl.fetch(str(cwd))
    if r.returncode:
        raise Abort("git fetch failed in %s:\n%s" % (cwd, r.stderr.strip()[-2000:]))


def say(msg):
    print("release: " + msg, flush=True)


def require_clean_main(wt, what):
    branch = git(wt, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        raise Abort("the %s checkout %s is on %s, not main" % (what, wt, branch))
    dirty = git(wt, "status", "--porcelain")
    if dirty:
        raise Abort("the %s checkout %s is dirty; commit or stash first:\n%s" % (what, wt, dirty))


def next_version(repo, minor):
    v = json.loads(git(repo, "show", "origin/main:" + PLUGIN))["version"]
    major, mi, patch = (int(x) for x in v.split("."))
    return "%d.%d.0" % (major, mi + 1) if minor else "%d.%d.%d" % (major, mi, patch + 1)


def set_version(text, new, after=0):
    """The first "version" at or after `after` set to `new`, the rest of the file as it was."""
    m = re.compile(r'("version"\s*:\s*")[^"]*(")').search(text, after)
    if not m:
        raise Abort("no version field to bump")
    return text[:m.start()] + m.group(1) + new + m.group(2) + text[m.end():]


def failure_report(out):
    """Every "FAIL:" and "ERROR:" section of unittest output with its traceback, then the "Ran N tests" and "FAILED (..)" lines."""
    keep, in_section = [], False
    for line in out.splitlines():
        if line.startswith(("FAIL: ", "ERROR: ")):
            in_section = True
        elif line.startswith("Ran ") or line.startswith("FAILED ("):
            in_section = False
            keep.append(line)
            continue
        if in_section:
            keep.append(line)
    return "\n".join(keep)


def save_output(out):
    """The full suite output, in the config dir: a file inside the checkout would make the tree dirty and block the release."""
    d = tl.config_dir() / "releases"
    d.mkdir(parents=True, exist_ok=True)
    f = d / ("suite-%s-%d.log" % (datetime.datetime.now().strftime("%Y%m%d-%H%M%S"), os.getpid()))
    f.write_text(out, encoding="utf-8")
    return f


def workers():
    """How many shards the suite runs in at once: TASK_LOOP_SUITE_WORKERS, else max(2, cpu count - 2)."""
    n = os.environ.get("TASK_LOOP_SUITE_WORKERS")
    return max(1, int(n)) if n and n.isdigit() else max(2, (os.cpu_count() or 1) - 2)


def isolated_env(home):
    """The environment of one shard: its own HOME, config dirs and temp dir, so shards do not share state under ~ or in /tmp.
    The real git config is copied in, since tests commit with the identity it holds."""
    home.mkdir(parents=True, exist_ok=True)
    for sub in ("tmp", ".config"):
        (home / sub).mkdir(exist_ok=True)
    real = Path.home() / ".gitconfig"
    if real.is_file():
        (home / ".gitconfig").write_bytes(real.read_bytes())
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               APPDATA=str(home / ".config"), TMPDIR=str(home / "tmp"), TEMP=str(home / "tmp"), TMP=str(home / "tmp"))
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(k, None)
    return env


def merge_outputs(parts, planned, wall=None):
    """One unittest-shaped output from the (name, returncode, output) of each shard: their text without their own summaries, then a
    single "Ran N tests in <wall>s" and "OK" / "FAILED (..)". A shard that died without a summary, or a count that is not the planned one, is an ERROR."""
    body, total, secs, bad = [], 0, 0.0, {"failures": 0, "errors": 0}
    other = {}
    for name, rc, out in parts:
        ran = re.search(r"^Ran (\d+) tests? in ([\d.]+)s$", out, re.M)
        if not ran:
            body.append("ERROR: shard %s crashed (exit %s) without a summary\n%s" % (name, rc, "\n".join(out.splitlines()[-40:])))
            bad["errors"] += 1
            continue
        total += int(ran.group(1))
        secs = max(secs, float(ran.group(2)))
        tail = re.search(r"^(?:OK|FAILED) ?\((.*)\)$", out, re.M)
        for k, v in re.findall(r"(\w[\w ]*?)=(\d+)", tail.group(1) if tail else ""):
            if k in bad:
                bad[k] += int(v)
            else:
                other[k] = other.get(k, 0) + int(v)
        cut = out.rfind("\n" + "-" * 70 + "\nRan ")
        body.append(out[:cut] if cut >= 0 else out)
        if rc and not (bad["failures"] or bad["errors"]):
            body.append("ERROR: shard %s exited %s but reported no failure" % (name, rc))
            bad["errors"] += 1
    if total != planned:
        body.append("ERROR: %d tests ran, %d were planned" % (total, planned))
        bad["errors"] += 1
    stats = ", ".join("%s=%d" % kv for kv in list(bad.items()) + sorted(other.items()) if kv[1])
    red = bad["failures"] or bad["errors"]
    secs = wall if wall is not None else secs
    summary = "Ran %d tests in %.3fs\n\n%s" % (total, secs, ("FAILED (%s)" % stats) if red else ("OK (%s)" % stats if stats else "OK"))
    return "\n".join(x for x in body if x.strip()) + "\n\n" + summary, not red


def suite(repo, record=False):
    """The whole suite as N parallel shards, each its own process with its own HOME, then the tests of tests/shard.py SERIAL in one process.
    record=True also writes every test's seconds to tests/durations.json (what the splitter balances on) when the run is green.
    Returns {"workers", "wall", "shards": {name: seconds}, "serial": seconds, "times": {test id: seconds}}."""
    n = workers()
    say("running the full suite in %d shards, then the serial group" % n)
    shard = [sys.executable, str(HERE.parent / "tests" / "shard.py")]
    root = str(Path(repo) / "tests")
    r = run(shard + ["plan", str(n), "--root", root], repo, check=False)
    try:
        plan = json.loads(r.stdout)
    except ValueError:
        out = (r.stdout + r.stderr).strip()
        log = save_output(out)
        raise Abort("the suite is red; nothing released:\ncould not plan the shards\n%s\nfull output: %s" % (out[-2000:], log), log)
    work = Path(tempfile.mkdtemp(prefix="tl-suite-"))
    began = time.monotonic()
    try:
        def start(name, ids):
            f = work / (name + ".ids")
            f.write_text("\n".join(ids) + "\n", encoding="utf-8")
            log = open(work / (name + ".log"), "w", encoding="utf-8", errors="replace")  # a file, not a pipe: a full pipe stalls the shard
            p = subprocess.Popen(shard + ["ids", str(f), "--root", root, "--times", str(work / (name + ".times"))], cwd=str(repo), env=isolated_env(work / name),
                                 stdout=log, stderr=subprocess.STDOUT, text=True)
            log.close()
            return name, p

        def finish(name, p):
            p.wait()
            return name, p.returncode, (work / (name + ".log")).read_text(encoding="utf-8", errors="replace")
        procs = [start("shard%d" % i, ids) for i, ids in enumerate(plan["shards"], 1) if ids]
        parts = [finish(name, p) for name, p in procs]
        serial_began = time.monotonic()
        if plan["serial"]:
            parts.append(finish(*start("serial", plan["serial"])))
        serial_wall = time.monotonic() - serial_began if plan["serial"] else 0.0
        times = {}
        for name, _ in procs + ([("serial", None)] if plan["serial"] else []):
            try:
                times.update(json.loads((work / (name + ".times")).read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out, green = merge_outputs(parts, sum(len(s) for s in plan["shards"]) + len(plan["serial"]),
                              time.monotonic() - began)
    tail = out.splitlines()
    if record and len(times) == len(set(times)) and len(times) >= sum(len(x) for x in plan["shards"]) + len(plan["serial"]):
        dur = Path(repo) / "tests" / "durations.json"
        dur.write_text(json.dumps({k: round(v, 3) for k, v in sorted(times.items())}, indent=0) + "\n", encoding="utf-8")
        say("recorded %d test durations in %s" % (len(times), dur))
    shard_wall = {}
    for name, _, o in parts:
        m = re.search(r"^Ran \d+ tests? in ([\d.]+)s$", o, re.M)
        if m:
            shard_wall[name] = float(m.group(1))
    say("shards: " + " ".join("%s=%.0fs" % kv for kv in sorted(shard_wall.items())))
    if not green:
        report = failure_report(out) or "\n".join(tail[-40:])
        log = save_output(out)
        tests = ["%s (%s)" % m for m in re.findall(r"^(?:FAIL|ERROR): (\S+) \(([^)]*)\)", out, re.M)]
        raise Abort("the suite is red; nothing released:\n%s\nfull output: %s" % (report, log), log, tests)
    say("suite green: " + " ".join(x for x in tail[-3:] if x.strip()))
    return {"workers": n, "wall": time.monotonic() - began, "shards": shard_wall, "serial": serial_wall, "times": times}


def container_suite(repo):
    """The suite through dev/suite-docker.py (a Linux container's own disk; the host suite when docker is not reachable).
    TASK_LOOP_SUITE_HOST=1 runs it on the host. Streams its output; red raises Abort like suite() does. The container's own log is gone with it, so the saved one is this output."""
    if os.environ.get("TASK_LOOP_SUITE_HOST") or not (Path(repo) / "dev" / "suite.py").is_file():  # a fake repo (the tests') has no runner of its own: the host runner
        return suite(repo)
    say("running the full suite in a container (dev/suite-docker.py)")
    p = subprocess.Popen([sys.executable, str(HERE / "suite-docker.py"), "--repo", str(repo)], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    lines = []
    for line in p.stdout:
        lines.append(line)
        sys.stdout.write(line)
        sys.stdout.flush()
    if p.wait() == 0:
        return
    out = "".join(lines)
    log = save_output(out)
    tests = ["%s (%s)" % m for m in re.findall(r"^(?:FAIL|ERROR): (\S+) \(([^)]*)\)", out, re.M)]
    raise Abort("the suite is red; nothing released:\n%s\nfull output: %s" % (failure_report(out) or "\n".join(lines[-40:]), log), log, tests)


def bump_and_commit(repo, message, minor):
    version = next_version(repo, minor)
    f = Path(repo) / PLUGIN
    f.write_text(set_version(f.read_text(encoding="utf-8"), version), encoding="utf-8")
    container_suite(repo)
    git(repo, "add", PLUGIN)
    git(repo, "commit", "-q", "-m", "%s: %s%s" % (version, message, TRAILER))
    return version


def push_main(repo, message, minor, version, base):
    """Push, under the land lock (an engine lands only while it holds it): an origin/main that moved since the bump (a
    land during the suite) is rebased onto, the version taken again and the suite run again, then pushed while no land
    can get in. A push refused all the same (one that skipped the lock) gets one more round. `base` is the origin/main the
    bump was built on: HEAD~1 is not, --from-branch puts the branch's commits between them."""
    url = git(repo, "remote", "get-url", "origin", check=False) or str(repo)
    with tl.os_lock(tl.land_lock_path(url), "release: " + message,
                    lambda who: say("waiting for the land lock (held by %s)" % who)):
        for _ in range(2):
            fetch(repo)
            head = git(repo, "rev-parse", "origin/main")
            if head != base:
                say("push race: origin/main %s is not the base %s; rebasing, taking the next version and running the suite again"
                    % (head, base))
                git(repo, "reset", "-q", "--hard", "HEAD~1")
                if run(["git", "-c", "rebase.updateRefs=false", "rebase", "-q", "origin/main"], repo, check=False).returncode:
                    run(["git", "rebase", "--abort"], repo, check=False)
                    raise Abort("the rebase onto origin/main after the push race failed")
                base = head
                version = bump_and_commit(repo, message, minor)
            r = run(["git", "push", "-q", "origin", "HEAD:main"], repo, check=False)
            if not r.returncode:
                return version
            fetch(repo)
            if git(repo, "rev-parse", "origin/main") == base:
                raise Abort("the push was refused and origin/main did not move:\n" + r.stderr)
    raise Abort("the push lost the race twice, the land lock held; nothing released")


def bump_marketplace(market, version):
    fetch(market)
    git(market, "merge", "-q", "--ff-only", "origin/main")
    f = Path(market) / MARKET
    text = f.read_text(encoding="utf-8")
    at = re.search(r'"name"\s*:\s*"%s"' % re.escape(NAME), text)
    if not at:
        raise Abort("%s has no %s entry" % (f, NAME))
    text = set_version(text, version, at.end())
    entry = [p for p in json.loads(text)["plugins"] if p.get("name") == NAME]
    if not entry or entry[0].get("version") != version:
        raise Abort("could not set %s's version in %s" % (NAME, f))
    f.write_text(text, encoding="utf-8")
    git(market, "commit", "-q", "-am", "%s %s%s" % (NAME, version, TRAILER))
    if run(["git", "push", "-q", "origin", "HEAD:main"], market, check=False).returncode:
        git(market, "pull", "-q", "--rebase", "origin", "main")
        git(market, "push", "-q", "origin", "HEAD:main")


def tag(cwd, name, what):
    """Tag HEAD of `cwd` as `name` and push the tag. Called only after the branch push succeeded. A tag that cannot be made or
    pushed is a warning: the release is out and must not be reported as failed for it."""
    if git(cwd, "rev-parse", "-q", "--verify", "refs/tags/" + name, check=False):
        say("warning: %s already has the tag %s; left as it is" % (what, name))
        return
    r = run(["git", "tag", name, "HEAD"], cwd, check=False)
    if not r.returncode:
        r = run(["git", "push", "-q", "origin", "refs/tags/" + name], cwd, check=False)
    if r.returncode:
        say("warning: tag %s in %s failed: %s" % (name, what, (r.stdout + r.stderr).strip()[-300:]))
    else:
        say("tagged %s in %s" % (name, what))


def install(repo, version):
    """Update the marketplace and the plugin, then check the new version's cache dir exists. A silent failure (0.23.0: a git
    fetch-pack error with exit 0) leaves the old version installed: run both commands once more, then fail loudly."""
    cache = tl.claude_dir() / "plugins" / "cache" / MARKETPLACE / NAME / version
    cmds = [["claude", "plugin", "marketplace", "update", MARKETPLACE], ["claude", "plugin", "update", "%s@%s" % (NAME, MARKETPLACE)]]
    failing, text = None, ""
    for attempt in (1, 2):
        for c in cmds:
            try:
                r = run(c, repo, check=False)
                rc, out = r.returncode, (r.stdout + r.stderr).strip()
            except OSError as e:
                rc, out = 127, str(e)
            if rc or c is cmds[-1]:
                failing, text = (c, out) if rc else (failing, out)
        if (cache / ".claude-plugin" / "plugin.json").is_file():
            say("installed: %s (%s)" % (version, cache))
            return
        say("install attempt %d left no %s; %s" % (attempt, cache, "trying once more" if attempt == 1 else "giving up"))
    raise Abort("the plugin install failed: %s is not installed (no %s).\nfailing command: %s\n%s"
                % (version, cache, " ".join(failing or cmds[-1]), text[-1000:]), version=version)


def release(a, repo, market):
    require_clean_main(repo, "main")
    require_clean_main(market, "marketplace")
    start = git(repo, "rev-parse", "HEAD")
    try:
        fetch(repo)
        git(repo, "merge", "-q", "--ff-only", "origin/main")
        base = git(repo, "rev-parse", "origin/main")
        if a.from_branch:
            b = a.from_branch
            if not git(repo, "rev-parse", "--verify", "-q", b + "^{commit}", check=False):
                b = "origin/" + a.from_branch
            if git(repo, "rev-list", "--max-count=1", "HEAD", "--not", "origin/main", b):
                raise Abort("main has unpublished commits absent from %s; nothing released" % a.from_branch)
            # Replay on main rather than checking out B: it may be in use in another worktree,
            # and releasing must not rewrite the source branch's ref, even with updateRefs enabled.
            git(repo, "reset", "-q", "--hard", b)
            git(repo, "-c", "rebase.updateRefs=false", "rebase", "-q", "origin/main")
        version = bump_and_commit(repo, a.message, a.minor)
        version = push_main(repo, a.message, a.minor, version, base)
    except Abort:
        run(["git", "rebase", "--abort"], repo, check=False)
        run(["git", "reset", "-q", "--hard", start], repo, check=False)
        raise
    say("pushed %s: %s" % (version, a.message))
    tag(repo, "v" + version, "the plugin repo")
    if a.bead:
        r = run(["bd", "close", a.bead, "--reason", a.reason or a.message], repo, check=False)
        if r.returncode:
            say("warning: bd close %s failed: %s" % (a.bead, (r.stdout + r.stderr).strip()[-300:]))
    try:
        bump_marketplace(market, version)
    except Abort as e:
        e.version = version
        raise
    say("marketplace at %s" % version)
    tag(market, "%s-v%s" % (NAME, version), "the marketplace")
    install(repo, version)
    return version


def record(result, a, repo):
    """releases/last.json: the latest release's result (a later success replaces a failure); and, when it failed, a comment on --bead."""
    d = tl.config_dir() / "releases"
    d.mkdir(parents=True, exist_ok=True)
    result.update(branch=a.from_branch or "main", message=a.message, at=time.time())
    f = d / "last.json"
    tmp = f.with_name("last.%d.tmp" % os.getpid())
    tmp.write_text(json.dumps(result, indent=1), encoding="utf-8")
    os.replace(tmp, f)
    if not result["ok"] and a.bead:
        text = "release FAILED: %s%s" % (result["summary"], ("; log " + result["log"]) if result.get("log") else "")
        r = run(["bd", "comment", a.bead, text], repo, check=False)
        if r.returncode:
            say("warning: bd comment %s failed: %s" % (a.bead, (r.stdout + r.stderr).strip()[-300:]))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="release.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("message")
    ap.add_argument("--bead", help="close this bead after the push")
    ap.add_argument("--reason", help="the close reason (default: the message)")
    ap.add_argument("--from-branch", help="rebase this branch onto origin/main in the release checkout under the release lock")
    ap.add_argument("--minor", action="store_true", help="bump the minor version, not the patch")
    ap.add_argument("--repo", default=tl.repo_root(str(HERE)), help="the main checkout (default: this repo's)")
    ap.add_argument("--marketplace", default=str(Path.home() / "Workspaces" / MARKETPLACE))
    a = ap.parse_args(argv)
    repo, market = tl.repo_root(a.repo), a.marketplace
    url = git(repo, "remote", "get-url", "origin", check=False) or repo
    path = tl.config_dir() / "locks" / ("release-%s.lock" % hashlib.sha1(url.encode()).hexdigest()[:12])
    holder = "pid %d since %s: %s" % (os.getpid(), datetime.datetime.now().strftime("%H:%M:%S"), a.message)
    try:
        with tl.os_lock(path, holder, lambda who: say("waiting for the release lock (held by %s)" % who)):
            version = release(a, repo, market)
        record({"ok": True, "version": version, "summary": "released " + version}, a, repo)
    except Abort as e:
        print("release: " + str(e), file=sys.stderr)
        first = str(e).strip().splitlines()[0] if str(e).strip() else "failed"
        summary = ("%s was pushed but " % e.version if e.version else "nothing released: ") + first
        record({"ok": False, "version": e.version, "summary": summary, "tests": e.tests, "log": e.log}, a, repo)
        print("release FAILED: " + summary + ((" (log %s)" % e.log) if e.log else ""), file=sys.stderr)  # the last line: a tail-reading watcher sees it
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
