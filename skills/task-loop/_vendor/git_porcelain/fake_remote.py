"""In-memory explicit remote refs, leases and scoped fetches."""

from __future__ import annotations

from typing import TYPE_CHECKING

from git_porcelain import fake_flow
from git_porcelain.api import CommandResult, Pushed, RefRejected, RemoteRejected, Sha, Transient
from git_porcelain.errors import GitReadFailure, GitUnavailable, MissingRemote
from git_porcelain.fake_store import ancestors
from git_porcelain.remote_validation import validate_delete_ref, validate_push, validate_remote

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from git_porcelain.api import PushResult
    from git_porcelain.fake_store import CheckoutState, RepoState


def _source(state: RepoState, remote: str) -> tuple[str, RepoState]:
    name = next((key for key, url in state.remotes.items() if url == remote), remote)
    there = fake_flow.remote_state(state, name)
    if isinstance(there, str):
        raise GitUnavailable(there)
    return name, there


def remote_url(state: RepoState, remote: str) -> str:
    if remote not in state.remotes:
        msg = f"error: No such remote '{remote}'"
        raise MissingRemote(msg)
    url = state.remotes[remote]
    matches = [
        (value, key[4:-10])
        for key, value in state.config.items()
        if key.startswith("url.") and key.endswith(".insteadof") and url.startswith(value)
    ]
    if matches:
        prefix, replacement = max(matches, key=lambda pair: len(pair[0]))
        return replacement + url[len(prefix) :]
    return url


def fetch(state: RepoState, remote: str, refspecs: Sequence[str]) -> CommandResult:
    validate_remote(remote)
    fake_flow.fetch_races(state)
    name, there = _source(state, remote)
    state.store.absorb(there.store)
    if not refspecs:
        fake_flow.fetch(state, name, retry=False)
        tip = there.refs.get(f"refs/heads/{there.default_branch}")
        if tip:
            state.refs["FETCH_HEAD"] = tip
        return CommandResult(ok=True, output="")
    for index, spec in enumerate(refspecs):
        src, colon, dst = spec.removeprefix("+").partition(":")
        ref = src if src in there.refs else f"refs/heads/{src}"
        sha = there.refs.get(ref, src if src in there.store.commits else None)
        if sha is None:
            msg = f"fatal: couldn't find remote ref {src}"
            raise GitUnavailable(msg)
        if index == 0:
            state.refs["FETCH_HEAD"] = sha
        if colon:
            state.refs[dst] = sha
        if ref.startswith("refs/heads/") and remote in state.remotes:
            state.refs[f"refs/remotes/{name}/{ref.removeprefix('refs/heads/')}"] = sha
    return CommandResult(ok=True, output="")


def delete_remote_at(state: RepoState, remote: str, ref: str, expected: Sha, *, missing_ok: bool = True) -> CommandResult:
    validate_remote(remote)
    validate_delete_ref(ref)
    try:
        name, there = _source(state, remote)
    except GitUnavailable as exc:
        if not missing_ok:
            raise
        msg = f"cannot verify remote deletion: {exc}"
        raise GitReadFailure(msg, output=exc.output, push_output=exc.output) from exc
    old = there.refs.get(ref)
    if old is None and missing_ok:
        return CommandResult(ok=True, output=f"To {remote}\n!\t:{ref}\t[rejected] (stale info)\nDone")
    if old != expected:
        msg = "[rejected] (stale info)"
        raise GitUnavailable(msg)
    refusal = fake_flow.hook_refusal(state, {})
    if refusal:
        raise GitUnavailable(refusal.tail, output=refusal.output)
    del there.refs[ref]
    if remote in state.remotes and ref.startswith("refs/heads/"):
        state.refs.pop(f"refs/remotes/{name}/{ref.removeprefix('refs/heads/')}", None)
    return CommandResult(ok=True, output=f"To {remote}\n-\t:{ref}\t[deleted]\nDone")


def _push_specs(state: RepoState, checkout: CheckoutState, name: str, refspecs: Sequence[str]) -> list[str]:
    if refspecs:
        return list(refspecs)
    branch = (checkout.head_ref or "").removeprefix("refs/heads/")
    configured = state.config.get(f"remote.{name}.push")
    if configured:
        return [configured]
    if state.config.get("push.default", "simple") not in {"simple", "upstream"}:
        msg = "fake push does not model this configured push.default mode"
        raise GitUnavailable(msg)
    if state.config.get(f"branch.{branch}.remote") == name:
        return [f"HEAD:{state.config.get(f'branch.{branch}.merge', checkout.head_ref or '')}"]
    msg = "fatal: The current branch has no upstream branch."
    raise GitUnavailable(msg)


def _resolve_push(
    state: RepoState, checkout: CheckoutState, spec: str, captured: str | None, *, options: Sequence[str]
) -> tuple[str, str | None]:
    src, colon, dst = spec.removeprefix("+").partition(":")
    if not colon:
        dst = checkout.head_ref if src == "HEAD" else src
    if not dst:
        msg = "push needs an explicit destination for detached HEAD"
        raise GitUnavailable(msg)
    if not dst.startswith("refs/"):
        dst = f"refs/heads/{dst}"
    if "--delete" in options or "-d" in options:
        src = ""
    sha = captured if src == "HEAD" else state.commit_named(src, checkout) if src else None
    if src and sha is None:
        msg = f"error: src refspec {src} does not match any"
        raise GitUnavailable(msg)
    return dst, sha


def _check_push(
    state: RepoState,
    there: RepoState,
    name: str,
    dst: str,
    sha: str | None,
    *,
    force: bool,
    options: Sequence[str],
) -> RefRejected | RemoteRejected | None:
    old = there.refs.get(dst)
    lease = next((opt for opt in options if opt == "--force-with-lease" or opt.startswith("--force-with-lease=")), None)
    if lease is not None:
        ref, colon, value = lease.partition("=")[2].partition(":")
        applies = not ref or ref == dst
        expected = value if colon else state.refs.get(f"refs/remotes/{name}/{dst.removeprefix('refs/heads/')}")
        if applies and old != (expected or None):
            return RefRejected("[rejected] (stale info)")
        force = force or applies
    if old is not None and sha is not None:
        if not force and old not in ancestors(state.store, sha):
            return RefRejected("[rejected] (non-fast-forward)")
        if (
            "--dry-run" not in options
            and there.config.get("receive.denynonfastforwards") == "true"
            and old not in ancestors(state.store, sha)
        ):
            return RemoteRejected("[remote rejected] (non-fast-forward)")
    return None


def _apply_push(state: RepoState, there: RepoState, name: str, dst: str, sha: str | None) -> None:
    there.store.absorb(state.store)
    if sha is None:
        there.refs.pop(dst, None)
    else:
        there.refs[dst] = sha
    if dst.startswith("refs/heads/"):
        tracking = f"refs/remotes/{name}/{dst.removeprefix('refs/heads/')}"
        if sha is None:
            state.refs.pop(tracking, None)
        else:
            state.refs[tracking] = sha


def _expand_spec(state: RepoState, there: RepoState, spec: str, *, prune: bool) -> list[str]:
    src, colon, dst = spec.removeprefix("+").partition(":")
    if "*" not in src or not colon or "*" not in dst:
        return [spec]
    prefix, _, suffix = src.partition("*")
    mapped = {
        dst.replace("*", ref[len(prefix) : len(ref) - len(suffix) if suffix else None]): ref
        for ref in state.refs
        if ref.startswith(prefix) and ref.endswith(suffix)
    }
    expanded = [("+" if spec.startswith("+") else "") + ref + ":" + target for target, ref in mapped.items()]
    if prune:
        start, _, end = dst.partition("*")
        expanded += [f":{ref}" for ref in there.refs if ref.startswith(start) and ref.endswith(end) and ref not in mapped]
    return expanded


def _requested_specs(
    state: RepoState, checkout: CheckoutState, name: str, there: RepoState, refspecs: Sequence[str], *, options: Sequence[str]
) -> list[str]:
    if "--mirror" in options:
        if refspecs:
            msg = "--mirror cannot be combined with refspecs"
            raise GitUnavailable(msg)
        return [f"+{ref}:{ref}" for ref in state.refs if ref.startswith("refs/")] + [
            f":{ref}" for ref in there.refs if ref.startswith("refs/") and ref not in state.refs
        ]
    return [
        expanded
        for spec in _push_specs(state, checkout, name, refspecs)
        for expanded in _expand_spec(state, there, spec, prune="--prune" in options)
    ]


def _validate_options(options: Sequence[str]) -> None:
    if any(
        opt not in {"--force-with-lease", "--force", "-f", "--dry-run", "--delete", "-d", "--mirror", "--prune"}
        and not opt.startswith("--force-with-lease=")
        for opt in options
    ):
        msg = "fake push does not model these push options"
        raise GitUnavailable(msg)


def _send_specs(
    state: RepoState, checkout: CheckoutState, name: str, there: RepoState, specs: Sequence[str], *, options: Sequence[str]
) -> PushResult:
    captured = state.head_sha(checkout)
    result_sha: str | None = None
    rows: list[str] = [f"To {name}"]
    refusals: list[RefRejected | RemoteRejected] = []
    for spec in specs:
        forced = spec.startswith("+") or "--force" in options or "-f" in options or "--mirror" in options
        dst, sha = _resolve_push(state, checkout, spec, captured, options=options)
        rejected = _check_push(state, there, name, dst, sha, force=forced, options=options)
        if rejected is not None:
            rows.append(f"!\t{spec}\t{rejected.tail}")
            refusals.append(rejected)
            continue
        old = there.refs.get(dst)
        if sha is None:
            flag, summary = "-", "[deleted]"
        elif old == sha:
            flag, summary = "=", "[up to date]"
        elif old is None:
            flag, summary = "*", "[new reference]"
        else:
            flag, summary = " ", f"{old[:7]}..{sha[:7]}"
        rows.append(f"{flag}\t{spec}\t{summary}")
        if "--dry-run" not in options:
            _apply_push(state, there, name, dst, sha)
            if sha is not None and result_sha is None:
                result_sha = sha
    output = "\n".join([*rows, "Done"])
    if refusals:
        output += f"\nerror: failed to push some refs to '{name}'"
        raced = len(refusals) == len(specs) and all(isinstance(refusal, RefRejected) for refusal in refusals)
        kind = RefRejected if raced else RemoteRejected
        return kind(refusals[0].tail, output=output)
    return Pushed(Sha(result_sha or ""), output=output)


def push_refspecs(
    state: RepoState,
    checkout: CheckoutState,
    remote: str,
    refspecs: Sequence[str],
    *,
    hook_env: Mapping[str, str] | None,
    options: Sequence[str] = (),
    force: bool = False,
    allow_delete: bool = False,
) -> PushResult:
    """Push explicit refs; deletion-only success carries an empty sha."""
    validate_push(remote, refspecs, options=options, force=force, allow_delete=allow_delete)
    refusal = fake_flow.hook_refusal(state, hook_env or {})
    if refusal:
        return refusal
    if state.hooks.push_transport_failure is not None:
        return Transient(state.hooks.push_transport_failure)
    try:
        name, there = _source(state, remote)
    except GitUnavailable as exc:
        return Transient(str(exc), output=exc.output)
    _validate_options(options)
    specs = _requested_specs(state, checkout, name, there, refspecs, options=options)
    return _send_specs(state, checkout, name, there, specs, options=options)


def push_request(
    state: RepoState,
    checkout: CheckoutState,
    remote: str | None,
    refspecs: Sequence[str],
    *,
    options: Sequence[str],
    hook_env: Mapping[str, str] | None,
    force: bool = False,
    allow_delete: bool = False,
) -> CommandResult:
    validate_push(remote, refspecs, options=options, force=force, allow_delete=allow_delete)
    branch = (checkout.head_ref or "").removeprefix("refs/heads/")
    name = (
        remote
        or state.config.get(f"branch.{branch}.pushremote")
        or state.config.get("remote.pushdefault")
        or state.config.get(f"branch.{branch}.remote", "origin")
    )
    try:
        result = push_refspecs(state, checkout, name, refspecs, hook_env=hook_env, options=options, force=force, allow_delete=allow_delete)
    except GitUnavailable as exc:
        return CommandResult(ok=False, output=exc.output)
    return CommandResult(ok=isinstance(result, Pushed), output=result.output)
