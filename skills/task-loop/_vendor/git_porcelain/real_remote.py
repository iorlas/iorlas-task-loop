"""Explicit fetch and push forms, preserving checkout environment and hooks."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from git_porcelain import real_commands, real_parse, real_write
from git_porcelain.api import HookRejected, Pushed, RefRejected, RemoteRejected, Sha, Transient
from git_porcelain.errors import GitReadFailure, GitUnavailable
from git_porcelain.real_done import unavailable
from git_porcelain.remote_validation import validate_delete_ref, validate_push, validate_remote

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from git_porcelain.api import CommandResult, PushResult
    from git_porcelain.real import RealRepo, RealWorktree


def fetch(repo: RealRepo, remote: str, refspecs: Sequence[str], timeout: float | None) -> None:
    validate_remote(remote)
    try:
        for attempt in range(5):
            done = repo.run(repo.path, "fetch", "--quiet", "--", remote, *refspecs, check=False, timeout=timeout)
            if done.rc == 0:
                return
            if attempt == 4 or not real_write.REF_RACE.search(done.out + done.err):
                raise unavailable(("fetch",), done)
            repo.sleep(0.1 * (attempt + 1))
    finally:
        repo.invalidate()


def delete_remote_at(repo: RealRepo, remote: str, ref: str, expected: Sha) -> None:
    validate_remote(remote)
    validate_delete_ref(ref)
    try:
        done = repo.run(repo.path, "push", f"--force-with-lease={ref}:{expected}", "--", remote, f":{ref}", check=False)
        if done.rc == 0:
            return
        try:
            found = repo.run(repo.path, "ls-remote", "--refs", "--", remote, ref)
        except GitUnavailable as exc:
            msg = f"cannot verify remote deletion: {exc}"
            raise GitReadFailure(msg) from exc
        for line in found.out.splitlines():
            oid, sep, name = line.partition("\t")
            if not sep or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid) or not name:
                msg = "ls-remote returned a malformed record"
                raise GitReadFailure(msg)
            if name == ref:
                raise unavailable(("push",), done)
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
                    raise GitUnavailable(msg)
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
    validate_push(remote, refspecs, options=options, force=force, allow_delete=allow_delete)
    specs = _pin(wt, refspecs)
    if remote is None and specs:
        branch = wt.branch()
        keys = [*([f"branch.{branch}.pushRemote"] if branch else []), "remote.pushDefault"]
        keys += [f"branch.{branch}.remote"] if branch else []
        for key in keys:
            configured = wt.run("config", "--get", key, check=False)
            if configured.rc == 0:
                remote = configured.out.strip()
                break
            if configured.rc != 1:
                raise unavailable(("config",), configured)
        remote = remote or "origin"
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
    """Push explicit refs; deletion-only success is Pushed(Sha("")), with nothing pushed."""
    validate_push(remote, refspecs, force=force, allow_delete=allow_delete)
    specs = _pin(wt, refspecs)
    try:
        done = wt.repo.run(wt.path, "push", "--porcelain", "--", remote, *specs, check=False, env=hook_env, timeout=timeout)
    finally:
        wt.repo.invalidate()
    output = (done.out + done.err).strip()
    if not done.rc:
        source = next((src for spec in specs if (src := spec.removeprefix("+").partition(":")[0])), None)
        if not specs:
            source = "HEAD"
        sha = wt.run("rev-parse", "--verify", source).out.strip() if source is not None else ""
        return Pushed(Sha(sha))
    if real_write.TRANSIENT.search(output):
        return Transient(output)
    refused = [row for row in real_parse.parse_push(done.out) if row.flag == "!"]
    if refused:
        if all(
            row.summary.startswith("[rejected]")
            and any(reason in row.summary for reason in ("non-fast-forward", "fetch first", "stale info"))
            for row in refused
        ):
            return RefRejected(output)
        return RemoteRejected(output)
    if "pre-push" in output or "failed to push some refs" in output:
        return HookRejected(output)
    raise unavailable(("push",), done)
