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
checkout, push it, `claude plugin marketplace update` and `claude plugin update`. Nothing is ever deleted: a plugin
cache dir a live engine runs from stays.

Run it from any worktree; it acts on the main checkout. Python 3.8+, standard library only.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
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
    pass


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


def suite(repo):
    say("running the full suite")
    r = run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], repo, check=False)
    out = (r.stdout + r.stderr).strip()
    tail = out.splitlines()
    if r.returncode:
        report = failure_report(out) or "\n".join(tail[-40:])
        raise Abort("the suite is red; nothing released:\n%s\nfull output: %s" % (report, save_output(out)))
    say("suite green: " + " ".join(x for x in tail[-3:] if x.strip()))


def bump_and_commit(repo, message, minor):
    version = next_version(repo, minor)
    f = Path(repo) / PLUGIN
    f.write_text(set_version(f.read_text(encoding="utf-8"), version), encoding="utf-8")
    suite(repo)
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
    if a.bead:
        r = run(["bd", "close", a.bead, "--reason", a.reason or a.message], repo, check=False)
        if r.returncode:
            say("warning: bd close %s failed: %s" % (a.bead, (r.stdout + r.stderr).strip()[-300:]))
    bump_marketplace(market, version)
    say("marketplace at %s" % version)
    run(["claude", "plugin", "marketplace", "update", MARKETPLACE], repo, check=False)
    r = run(["claude", "plugin", "update", "%s@%s" % (NAME, MARKETPLACE)], repo, check=False)
    tail = (r.stdout + r.stderr).strip().splitlines()
    say("installed: " + (tail[-1] if tail else "rc %d" % r.returncode))
    return version


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
            release(a, repo, market)
    except Abort as e:
        print("release: " + str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
