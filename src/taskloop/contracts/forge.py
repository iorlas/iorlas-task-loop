"""A pull request as the forge shows it, and one branch of a stack to deliver."""
from typing import final

import msgspec

from taskloop.contracts.wire import Rec

OPEN, MERGED, CLOSED = "OPEN", "MERGED", "CLOSED"


@final
class Pr(Rec):
    """What `gh pr view --json` says of one PR. `merge_sha` is the commit the forge made on the base when it merged ("" until then)."""

    number: int
    state: str
    head_ref: str
    head_oid: str
    base_ref: str
    merge_sha: str = ""
    url: str = ""
    title: str = ""


@final
class StackItem(Rec):
    """One thing to deliver: a branch, or a PR that exists already (`pr`). `bead` is the bead its land is recorded on ("" records none);
    `supersedes` an older PR to close once this one has merged."""

    branch: str = ""
    pr: int = 0
    bead: str = ""
    supersedes: int = 0


@final
class _Oid(Rec, rename="camel"):
    oid: str


@final
class _GhPr(Rec, rename="camel", forbid_unknown_fields=False):
    """`gh pr view --json number,state,headRefName,headRefOid,baseRefName,mergeCommit,url,title`, as gh prints it."""

    number: int
    state: str
    head_ref_name: str
    head_ref_oid: str
    base_ref_name: str
    merge_commit: _Oid | None = None
    url: str = ""
    title: str = ""


def gh_pr(data: object) -> Pr:
    """The Pr gh's JSON object is; msgspec.ValidationError when it is no PR."""
    g = msgspec.convert(data, _GhPr)
    return Pr(number=g.number, state=g.state, head_ref=g.head_ref_name, head_oid=g.head_ref_oid, base_ref=g.base_ref_name,
              merge_sha=g.merge_commit.oid if g.merge_commit else "", url=g.url, title=g.title)
