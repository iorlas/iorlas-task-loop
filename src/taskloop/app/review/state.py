"""What the review stage keeps between its steps, in one object the engine holds as `engine.review`. `unchecked` and `unverified` are
the two lists of the checkpoint's `ReviewState` (run/review_glue.py converts at the seams, so the record on disk is the one it always
was); write, land and the shell still read and write them, so they stay one shared instance until those stages have their own ports
(docs/design/b-review.md, decision 1). The rest is the stage's own and is not saved."""
from collections.abc import Callable
from typing import Any

from taskloop.contracts.wire import Open


class ReviewLive:
    def __init__(self) -> None:
        self.unchecked: list[Open] = []  # what the last review of this run says nobody checked (each review re-judges it)
        self.unverified: list[Open] = []  # tl-bxk.10.28: items that land for the owner
        self.verified: list[Open] = []  # the verifier's answer per unchecked item at land: in the trace and on the bead
        self.link_ok: set[str] = set()  # tl-bxk.7: links opened from this host
        self.link_bad: dict[str, str] = {}
        self.link_tries: dict[str, int] = {}
        self.link_fn: Callable[..., Any] | None = None  # a test's check

    def add_verified(self, u: Open, verdict: str, why: str, evidence: str) -> None:
        """The verifier's (or the engine's) answer for one unchecked item."""
        self.verified.append({"what": u["what"], "kind": u["kind"], "verdict": verdict, "why": why, "evidence": evidence})

    def add_unverified(self, u: Open, why: str) -> None:
        """An item that lands for the owner; once per text."""
        if u["what"] not in {x["what"] for x in self.unverified}:
            self.unverified.append({"what": u["what"], "kind": u["kind"], "why": why, "source": u.get("source") or ""})
