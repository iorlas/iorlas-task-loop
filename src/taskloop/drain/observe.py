"""Native, boot-aware drain observations through shelf. No spawn, signalling or log reads."""

import os

from stream_proc import group_alive, inspect_process, observe_owned

from taskloop.drain.models import Identity, Owner, Role, Seen


def identity() -> Identity | None:
    found = inspect_process(os.getpid())
    process = found.identity
    if found.kind != "matching" or process is None:
        return None
    return Identity(pid=process.pid, pgid=process.pgid, start=process.start, boot=process.boot)


def observe(owner: Owner) -> Seen:
    process = owner.identity
    seen = observe_owned(process.owned())
    if seen.kind == "matching":
        return Seen.ALIVE
    me = identity()
    if me is None:
        return Seen.UNKNOWN
    if process.boot != me.boot:
        return Seen.GONE
    if seen.kind in {"different_process", "unknown"}:
        return Seen.UNKNOWN
    if group_alive(process.pgid):
        return Seen.UNKNOWN if owner.role is Role.CALLER else Seen.ALIVE
    return Seen.GONE
