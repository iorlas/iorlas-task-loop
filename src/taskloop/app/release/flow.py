"""One release, start to end: the clone, the gate and suite, the bump, the push, the marketplace, the install, the record."""
import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from taskloop.adapters import beadtools, gitrepo, landlock
from taskloop.adapters.ident import config_dir
from taskloop.adapters.versionfile import NoVersion, set_version
from taskloop.app.release import clone, manifest, publish, selfupdate, shell, suite, tidy
from taskloop.app.release.push import push_main, release_lock_path
from taskloop.app.release.shell import Abort, Shell, say
from taskloop.contracts.env import Env
from taskloop.contracts.ids import MARKETPLACE, BeadId, parse_bead_id
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure, BeadQuery, Beads, Git, Spawner
from taskloop.contracts.snapshots import ReleaseResult
from taskloop.contracts.stores import ReleaseResultStore


@dataclass(frozen=True)
class Request:
    message: str
    bead: BeadId | None = None
    reason: str = ""
    from_branch: str = ""
    minor: bool = False


def next_version(where: Path, minor: bool, sh: Shell) -> str:
    v = json.loads(publish.git_must(lambda: sh.port.show(str(where), "origin/main", publish.PLUGIN), where))["version"]
    major, mi, patch = (int(x) for x in v.split("."))
    return f"{major}.{mi + 1}.0" if minor else f"{major}.{mi}.{patch + 1}"


def require_clean_main(wt: Path, what: str, sh: Shell) -> None:
    branch = publish.git_must(lambda: sh.port.branch(str(wt)), wt)
    if branch != "main":
        raise Abort(f"the {what} checkout {wt} is on {branch or 'a detached HEAD'}, not main")
    dirty = "\n".join(f"{r.index}{r.work} {r.path}" for r in publish.git_must(lambda: sh.port.status(str(wt)), wt))
    if dirty:
        raise Abort(f"the {what} checkout {wt} is dirty; commit or stash first:\n{dirty}")


def bump_and_commit(tool_root: Path, where: Path, req: Request, sh: Shell) -> str:
    """The next version committed as the only change, then the gate and the suite on exactly that commit's tree (what gets pushed)."""
    version = next_version(where, req.minor, sh)
    f = where / publish.PLUGIN
    try:
        f.write_text(set_version(f.read_text(encoding="utf-8"), version), encoding="utf-8")
    except NoVersion as e:
        raise Abort(str(e)) from None
    manifest.write(where, publish.git_must(lambda: sh.port.ls_files(str(where)), where))  # after the bump: it lists plugin.json as it ships
    publish.git_must(lambda: sh.port.stage(str(where), publish.PLUGIN, manifest.NAME), where)
    publish.git_must(lambda: sh.port.commit_staged(str(where), f"{version}: {req.message}{publish.TRAILER}"), where)
    suite.verify(tool_root, where, sh)
    return version


def refuse_open_children(req: Request, repo: Path, store: Beads | None) -> None:
    """--bead names the work this release finishes: a bead with an open child is only half done (tl-t7i.5 was closed with its other half
    open). Refused before anything is pushed. A bd that cannot be asked does not stop the release (the close itself reports that)."""
    if not req.bead:
        return
    try:
        kids = [b.id for b in (store or beadtools.bd_store(repo)).find(BeadQuery()) if b.parent == req.bead]
    except (BdFailure, SystemExit):
        return
    if kids:
        raise Abort(f"--bead {req.bead} has open children ({', '.join(sorted(kids))}): finish or close them, or release without --bead")


def close_bead(req: Request, repo: Path, store: Beads | None) -> None:
    if not req.bead:
        return
    try:
        (store or beadtools.bd_store(repo)).close(req.bead, req.reason or req.message)
    except (BdFailure, SystemExit) as e:
        say("warning: bd close {} failed: {}".format(req.bead, str(getattr(e, "error", e))[-300:]))


def release(req: Request, repo: Path, market: Path, tool_root: Path, sh: Shell, store: Beads | None = None) -> str:
    """Release `repo` from the clone: its main checkout may be dirty or on any branch and is left as it was. The marketplace
    checkout must be clean on main (it is pushed from)."""
    refuse_open_children(req, repo, store)
    require_clean_main(market, "marketplace", sh)
    url = sh.port.remote_url(str(repo), "origin")
    if not url:
        raise Abort(f"{repo} has no origin remote")
    where = clone.ready(config_dir(), url, sh)
    tip = sh.port.rev_parse(str(repo), "refs/heads/" + req.from_branch) if req.from_branch else ""
    if req.from_branch:
        clone.replay_branch(where, repo, req.from_branch, sh)
    base = sh.port.rev_parse(str(where), "origin/main")
    def again() -> str:
        return bump_and_commit(tool_root, where, req, sh)
    version = push_main(where, req.message, again(), base, again, sh)
    say(f"pushed {version}: {req.message}")
    publish.tag(where, "v" + version, "the plugin repo", sh)
    close_bead(req, repo, store)
    try:
        publish.bump_marketplace(market, version, sh)
    except Abort as e:
        e.version = version
        raise
    say(f"marketplace at {version}")
    publish.tag(market, f"{publish.NAME}-v{version}", "the marketplace", sh)
    publish.install(where, version, sh)
    drop_landed_branch(req, repo, where, tip, sh)
    return version


def drop_landed_branch(req: Request, repo: Path, where: Path, tip: str, sh: Shell) -> None:
    """--from-branch, after the push and the install: B's worktrees and B go, only when B's tip (as the replay took it) is on origin/main
    patch for patch. Whatever git keeps (changes, a lock) stays and is said; this never fails a release."""
    if not (req.from_branch and tip and tidy.on_base(sh.port, str(where), tip)):
        return
    kept = tidy.drop_branch(sh.port, str(repo), req.from_branch, tip)
    for line in kept:
        say(line)
    if not kept:
        say(f"removed branch {req.from_branch} and its worktrees")


def record(result: ReleaseResult, req: Request, repo: Path, store: Beads | None = None) -> None:
    """releases/last.json: the latest release's result (a later success replaces a failure); and, when it failed, a comment on --bead."""
    ReleaseResultStore(ConfigDir(config_dir())).write(result)
    if not result.ok and req.bead:
        text = "release FAILED: {}{}".format(result.summary, ("; log " + result.log) if result.log else "")
        try:
            (store or beadtools.bd_store(repo)).add_comment(req.bead, text)
        except (BdFailure, SystemExit) as e:
            say("warning: bd comment {} failed: {}".format(req.bead, str(getattr(e, "error", e))[-300:]))


def main(argv: list[str] | None, tool_root: Path, spawner: Spawner, port: Git, env: Env, doc: str = "") -> int:
    """One release from the command line; every process it starts goes through `spawner` (the edge makes it)."""
    sh = shell.of(spawner, port, env)
    ap = argparse.ArgumentParser(prog="release.py", description=doc)
    ap.add_argument("message")
    ap.add_argument("--bead", type=parse_bead_id, default=None, help="close this bead after the push")
    ap.add_argument("--reason", default="", help="the close reason (default: the message)")
    ap.add_argument("--from-branch", default="", help="replay this branch's commits on origin/main in the release clone")
    ap.add_argument("--minor", action="store_true", help="bump the minor version, not the patch")
    ap.add_argument("--repo", default=gitrepo.repo_root(str(tool_root)), help="the main checkout (default: this repo's)")
    ap.add_argument("--marketplace", default=str(Path.home() / "Workspaces" / MARKETPLACE))
    a = ap.parse_args(argv)
    req = Request(a.message, a.bead, a.reason, a.from_branch, a.minor)
    repo, market = Path(gitrepo.repo_root(a.repo)), Path(a.marketplace)
    url = sh.port.remote_url(str(repo), "origin") or str(repo)
    holder = f"pid {os.getpid()} since {time.strftime('%H:%M:%S')}: {req.message}"
    try:
        path = release_lock_path(config_dir(), url)
        newer = None
        with landlock.os_lock(path, holder, lambda who: say(f"waiting for the release lock (held by {who})")):
            newer = selfupdate.newer_release(tool_root, clone.ready(config_dir(), url, sh), sh)
            version = "" if newer else release(req, repo, market, tool_root, sh)
        if newer:  # the lock is released above: the exec'd release takes it
            selfupdate.exec_release(newer, sys.argv[1:] if argv is None else argv, repo, env)
        record(ReleaseResult(ok=True, version=version, summary="released " + version, at=time.time(), branch=req.from_branch or "main",
                             message=req.message), req, repo)
    except Abort as e:
        print("release: " + str(e), file=sys.stderr)
        first = str(e).strip().splitlines()[0] if str(e).strip() else "failed"
        summary = (f"{e.version} was pushed but " if e.version else "nothing released: ") + first
        record(ReleaseResult(ok=False, version=e.version, summary=summary, tests=list(e.tests), log=e.log, at=time.time(),
                             branch=req.from_branch or "main", message=req.message), req, repo)
        print("release FAILED: " + summary + ((f" (log {e.log})") if e.log else ""), file=sys.stderr)
        return 1
    return 0
