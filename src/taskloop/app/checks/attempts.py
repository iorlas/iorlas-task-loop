"""Attempts: one check run until it is decided: passed, red for good, timed out, or held by an editor lock and waited out."""
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from taskloop.app.checks.base import BaseCheck
from taskloop.app.checks.host import CheckHost
from taskloop.contracts.argv import argv_of
from taskloop.contracts.checks import Check
from taskloop.contracts.enums import WaitWhat
from taskloop.contracts.paths import RepoDirs
from taskloop.domain.checks import matchers, retry


@dataclass
class Outcome:
    rc: int
    tail: str  # the last lines of the last run's output
    seen: str  # all of its output
    tries: int
    secs: float  # of the last run
    base_red: bool = False
    wall_hit: bool = False  # stopped at the check's wall limit


class Attempts:
    def __init__(self, host: CheckHost, base: BaseCheck, sleep: Callable[[float], None] = time.sleep) -> None:
        self.host, self.base, self.sleep = host, base, sleep

    def run(self, c: Check, log: Path, env: Mapping[str, str]) -> Outcome:
        """Run the check; a red one again when that can change the answer: only when the first two failures differ, never for a hang,
        a timeout or a compile error."""
        tries, prior = 0, ""
        while True:
            tries += 1
            rc, tail, seen, took = self._once(c, log, env)
            out = Outcome(rc, tail, seen, tries, took, wall_hit=self.host.wall_hit)
            if rc in {0, 124}:
                self._say_stop(c, out)
                return out
            sig = matchers.output_signature(seen)
            kind = matchers.failure_kind(seen)
            if kind == "lock":
                return self._wait_lock(c, log, env, out)
            if tries == 1 and c.repo and self.base.red(c):
                return Outcome(rc, tail, seen, tries, took, base_red=True, wall_hit=self.host.wall_hit)
            if not self._again(c, out, tries, sig, prior):
                return out
            prior = sig

    def _once(self, c: Check, log: Path, env: Mapping[str, str]) -> tuple[int, str, str, float]:
        t0 = time.time()
        art = RepoDirs(self.host.wt).artifacts(self.host.bead)
        art.mkdir(parents=True, exist_ok=True)  # where a check may drop pictures: ingest copies them at step end
        rc, tail = self.host.sh(argv_of(c.cmd), timeout=c.wall_min * 60, save=log, what="check",
                                env={**env, "TL_ARTIFACTS": str(art), "TL_ARTIFACT_STEP": c.id})
        seen = self._read(log, tail)
        took = time.time() - t0
        self.host.waits.note_slot_waits(seen, took)
        return rc, tail, seen, took

    @staticmethod
    def _read(log: Path, fallback: str) -> str:
        try:
            return log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return fallback

    def _say_stop(self, c: Check, out: Outcome) -> None:
        if out.rc == 124 and c.retry:  # the engine's timeout or the command's own: a rerun hangs the same way
            self.host.warn(f"`{c.id}` failed (exit 124), no retry: timed out after {round(out.secs / 60, 1):g} min")

    def _again(self, c: Check, out: Outcome, tries: int, sig: str, prior: str) -> bool:
        if matchers.failure_kind(out.seen) == "deterministic":  # a rerun fails the same way, seconds later
            if c.retry:
                self.host.warn(f"`{c.id}` failed (exit {out.rc}) with a compile error: not retried")
            return False
        if not retry.retry_allowed(c.retry, tries, out.seen):
            return False
        if prior and sig == prior:
            self.host.warn(f"`{c.id}` failed twice with the same output: not retried")
            return False
        self.host.warn(f"`{c.id}` failed (exit {out.rc}), retrying: it is marked flaky")
        return True

    def _wait_lock(self, c: Check, log: Path, env: Mapping[str, str], out: Outcome) -> Outcome:
        """An editor or project lock: wait, then rerun, 15/30/60 s up to 5 min in all."""
        rc, tail, seen = out.rc, out.tail, out.seen
        started = time.time() - out.secs
        for n, wait in enumerate(retry.lock_waits(), 1):
            self.host.warn(f"`{c.id}` is held by an editor or project lock; waiting {wait} s ({n})")
            wid = self.host.waits.start(WaitWhat.EDITOR_LOCK)
            self.sleep(wait)
            self.host.waits.add(wait, WaitWhat.EDITOR_LOCK, wid)
            rc, tail = self.host.sh(argv_of(c.cmd), timeout=c.wall_min * 60, save=log, env=env, what="check")
            seen = self._read(log, tail)
            self.host.waits.note_slot_waits(seen, time.time() - started)
            if rc == 0 or matchers.failure_kind(seen) != "lock":
                break
        if rc and matchers.failure_kind(seen) == "lock":
            tail += f"\n(still locked after {retry.LOCK_WAIT_MAX} s of waiting)"
        return Outcome(rc, tail, seen, out.tries, out.secs, wall_hit=self.host.wall_hit)
