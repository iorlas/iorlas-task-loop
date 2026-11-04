"""Explicit fetch and push forms, preserving checkout environment and hooks."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from git_porcelain import real_commands, real_parse, real_write
from git_porcelain.api import CommandResult, HookRejected, Pushed, RefRejected, RemoteRejected, Sha, Transient
from git_porcelain.errors import GitReadFailure, GitUnavailable, RefRace
from git_porcelain.real_done import unavailable
from git_porcelain.remote_validation import validate_delete_ref, validate_push, validate_remote

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from git_porcelain.api import PushResult
    from git_porcelain.real import RealRepo, RealWorktree
    from git_porcelain.real_done import Done


def fetch_done(repo: RealRepo, remote: str, refspecs: Sequence[str], timeout: float | None) -> Done:
    """Retry only ref races, with at most five single-process attempts."""
    attempt = 0
    while True:
        done = repo.run(repo.path, "fetch", "--quiet", "--", remote, *refspecs, check=False, timeout=timeout)
        if not done.rc or attempt == 4 or not isinstance(unavailable(("fetch",), done), RefRace):
            return done
        repo.sleep(0.1 * (attempt + 1))
        attempt += 1


def fetch(repo: RealRepo, remote: str, refspecs: Sequence[str], timeout: float | None) -> CommandResult:
    validate_remote(remote)
    try:
        done = fetch_done(repo, remote, refspecs, timeout)
        if done.rc:
            raise unavailable(("fetch",), done)
        return CommandResult(ok=True, output=done.output)
    finally:
        repo.invalidate()


def delete_remote_at(repo: RealRepo, remote: str, ref: str, expected: Sha, *, missing_ok: bool = True) -> CommandResult:
    """Delete with one push; missing_ok=False returns that invocation's refusal immediately.

    The default preserves idempotency: a refused lease requires one additional ls-remote,
    because push's stale-info row cannot distinguish an absent ref from a moved ref.
    """
    validate_remote(remote)
    validate_delete_ref(ref)
    try:
        done = repo.run(repo.path, "push", "--porcelain", f"--force-with-lease={ref}:{expected}", "--", remote, f":{ref}", check=False)
        if done.rc == 0:
            return CommandResult(ok=True, output=done.output)
        if not missing_ok:
            raise unavailable(("push",), done)
        try:
            found = repo.run(repo.path, "ls-remote", "--refs", "--", remote, ref)
        except GitUnavailable as exc:
            msg = f"cannot verify remote deletion: {exc}"
            raise GitReadFailure(msg, output=exc.output, push_output=done.output) from exc
        for line in found.out.splitlines():
            oid, sep, name = line.partition("\t")
            if not sep or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid) or not name:
                msg = "ls-remote returned a malformed record"
                raise GitReadFailure(msg, output=found.output, push_output=done.output)
            if name == ref:
                raise unavailable(("push",), done)
        return CommandResult(ok=True, output=done.output)
    finally:
        repo.invalidate()


def _pin(wt: RealWorktree, refspecs: Sequence[str]) -> tuple[str, ...]:
    captured: str | None = None
    pinned: list[str] = []
    for spec in refspecs:
        force = "+" if spec.startswith("+") else ""
        source, colon, destination = spec.removeprefix("+").partition(":")
        if source == "HEAD":
            if captured is None:
                captured = wt.run("rev-parse", "--verify", "HEAD").out.strip()
            # Bare HEAD still names the current branch's destination after pinning its source.
            source = captured
            if not colon:
                branch = wt.run("symbolic-ref", "--quiet", "HEAD", check=False)
                if branch.rc:
                    msg = "a bare HEAD push needs a symbolic branch or an explicit destination"
                    raise GitUnavailable(msg, output=branch.output)
                colon, destination = ":", branch.out.strip()
        pinned.append(force + source + colon + destination)
    return tuple(pinned)


def push_request(
    wt: RealWorktree,
    remote: str | None,
    refspecs: Sequence[str],
    *,
    options: Sequence[str],
    hook_env: Mapping[str, str] | None,
    timeout: float | None,
    force: bool = False,
    allow_delete: bool = False,
) -> CommandResult:
    """One push process with an explicit remote (or no refspecs).

    Git's positional syntax cannot pass refspecs without naming a repository. With remote=None
    and explicit refspecs, symbolic-ref and one config query select its configured push remote
    before the push: three processes. Passing the remote avoids both discovery calls.
    """
    validate_push(remote, refspecs, options=options, force=force, allow_delete=allow_delete)
    # Command-style pushes need no returned SHA: let git resolve HEAD in its own invocation.
    specs = tuple(refspecs)
    if remote is None and specs:
        branch = wt.branch()
        keys = [*([f"branch.{branch}.pushremote"] if branch else []), "remote.pushdefault"]
        keys += [f"branch.{branch}.remote"] if branch else []
        configured = wt.run("config", "--null", "--get-regexp", r"^(branch\..*\.(pushremote|remote)|remote\.pushdefault)$", check=False)
        if configured.rc not in {0, 1}:
            raise unavailable(("config",), configured)
        values = dict(record.split("\n", 1) for record in configured.out.split("\0") if "\n" in record)
        remote = next((values[key] for key in keys if key in values), "origin")
    validate_remote(remote)
    return real_commands.command(
        wt, ["push", *options, "--", *([remote] if remote is not None else []), *specs], env=hook_env, timeout=timeout
    )


def push_refspecs(
    wt: RealWorktree,
    remote: str,
    refspecs: Sequence[str],
    *,
    hook_env: Mapping[str, str] | None,
    timeout: float | None,
    force: bool = False,
    allow_delete: bool = False,
) -> PushResult:
    """Push explicit refs; deletion-only success is Pushed(Sha("")), with nothing pushed.

    Full object ids and deletion-only requests cost one process. A symbolic source needs one
    resolution process because push porcelain omits the full oid for new/up-to-date refs.
    Bare HEAD also needs symbolic-ref to preserve its implicit branch destination.
    """
    validate_push(remote, refspecs, force=force, allow_delete=allow_delete)
    specs = _pin(wt, refspecs)
    source = next((src for spec in specs if (src := spec.removeprefix("+").partition(":")[0])), None)
    if not specs:
        source = "HEAD"
    sha = source or ""
    if source is not None and re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", source) is None:
        sha = wt.run("rev-parse", "--verify", "--end-of-options", source).out.strip()
    try:
        done = wt.repo.run(wt.path, "push", "--porcelain", "--", remote, *specs, check=False, env=hook_env, timeout=timeout)
    finally:
        wt.repo.invalidate()
    return classify_push(done, Sha(sha))


def classify_push(done: Done, sha: Sha) -> PushResult:
    """Classify only porcelain ref status and actual hook execution, retaining all output."""
    output = done.output
    if not done.rc:
        return Pushed(sha, output=output)
    rows = real_parse.parse_push(done.out)
    refused = [row for row in rows if row.flag == "!"]
    if refused:
        if len(refused) == len(rows) and all(
            row.summary.startswith("[rejected]")
            and any(reason in row.summary for reason in ("non-fast-forward", "fetch first", "stale info"))
            for row in refused
        ):
            return RefRejected(done.tail, output=output)
        return RemoteRejected(done.tail, output=output)
    if not rows and any(name == "pre-push" and code != 0 for name, code in done.hook_exits):
        return HookRejected(done.tail, output=output)
    if real_write.TRANSIENT.search(output):
        return Transient(done.tail, output=output)
    raise unavailable(("push",), done)
