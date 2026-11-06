"""The breaker: a pure fold of facts into a `State`, and a `view` that answers "may this key launch at time t". No clock, no I/O.

The same facts replayed in time order give the same answer, so a past incident is a regression fixture.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from any_breaker.fact import OK, RELEASE, Fact, Policy
from any_breaker.state import KEEP_FAILURES, Failure, KeyState, OutState, State, Strike

if TYPE_CHECKING:
    from collections.abc import Iterable

OPEN, CLOSED, OUT = "open", "closed", "out"


@dataclass(frozen=True)
class View:
    """One key at one time. `usable` is False while a bench or an out runs. Once it ends the key is closed with `canary` True: the next
    launch is the one probe before full traffic."""

    state: str = CLOSED
    usable: bool = True
    canary: bool = False
    until: float | None = None
    source: str | None = None
    kind: str | None = None
    evidence: str = ""
    rung: int = 0
    recent: tuple[Failure, ...] = ()


class Breaker:
    def __init__(self, policy: Policy | None = None) -> None:
        self.policy = policy or Policy()

    def step(self, state: State, fact: Fact) -> None:
        """Apply one fact to `state` (mutates). Facts must come in time order."""
        state.ts = max(state.ts, fact.ts)
        if fact.kind == RELEASE:
            self._release(state, fact)
        elif fact.kind == OK:
            state.outs.pop(fact.key, None)
            k = state.keys.setdefault(fact.key, KeyState())
            k.streak, k.rung, k.until, k.kind, k.fp, k.evidence, k.source, k.last_ok = [], 0, 0.0, None, None, "", None, fact.ts
        elif fact.kind in self.policy.outs:
            state.outs[fact.key] = self._out(fact)
        else:
            self._fail(state.keys.setdefault(fact.key, KeyState()), fact)

    def fold(self, facts: Iterable[Fact], state: State | None = None) -> State:
        """The state after `facts` on top of `state` (a checkpoint, else empty), which is left untouched. Facts at or before the
        checkpoint's ts are skipped, so fold(all) == fold(tail, fold(head)): the checkpoint is a cache, never truth."""
        out = copy.deepcopy(state) if state is not None else State()
        for f in sorted((f for f in facts if f.ts > out.ts), key=lambda f: f.ts):
            self.step(out, f)
        return out

    def view(self, state: State, key: str, t: float) -> View:
        o, k = state.outs.get(key), state.keys.get(key)
        recent = tuple(k.recent) if k else ()
        rung = k.rung if k else 0
        if o and t < o.until:
            return View(OUT, usable=False, until=o.until, source=o.source, kind=o.kind, evidence=o.evidence, rung=rung, recent=recent)
        canary, kind, evidence = bool(o), o.kind if o else None, o.evidence if o else ""
        if k and k.rung:
            if t < k.until:
                return View(
                    OPEN,
                    usable=False,
                    canary=bool(o),
                    until=k.until,
                    source=k.source,
                    kind=k.kind,
                    evidence=k.evidence,
                    rung=rung,
                    recent=recent,
                )
            canary, kind, evidence = True, k.kind, k.evidence
        return View(CLOSED, usable=True, canary=canary, kind=kind, evidence=evidence, rung=rung, recent=recent)

    def _release(self, state: State, fact: Fact) -> None:
        def hit(key: str) -> bool:
            return key.startswith(fact.key) if fact.prefix else key == fact.key

        for table in (state.outs, state.keys):
            for key in [k for k in table if hit(k)]:
                del table[key]

    def _out(self, fact: Fact) -> OutState:
        out = self.policy.outs[fact.kind]
        if fact.until is not None and fact.until > fact.ts:
            until, source = fact.until, "vendor"
        else:
            until, source = fact.ts + out.wait_s, out.source
        return OutState(fact.kind, float(until), source, fact.note[:240], fact.ts)

    def _fail(self, k: KeyState, f: Fact) -> None:
        pol, ts = self.policy, f.ts
        k.recent = [*k.recent, Failure(ts, f.kind, f.note[:120])][-KEEP_FAILURES:]
        if ts < k.until:  # launched before the bench began (a call already in flight): it does not count again
            return
        n, window_s, distinct = pol.rule(f.kind)
        fp = f.fp or f.kind
        probation = k.rung > 0 and ts >= k.until  # the canary failed: the next rung starts at once
        k.streak = [s for s in k.streak if ts - s.ts <= window_s and s.kind == f.kind] + [Strike(ts, f.kind, fp, f.source)]
        same = [s for s in k.streak if s.fp == fp]
        if probation or (len(same) >= n and len({s.source for s in same}) >= distinct):
            k.rung = min(k.rung + 1, len(pol.ladder_s))
            k.until = ts + pol.ladder_s[k.rung - 1]
            k.kind, k.fp, k.evidence, k.source = f.kind, fp, f.note[:240], "breaker"
            k.streak = []
