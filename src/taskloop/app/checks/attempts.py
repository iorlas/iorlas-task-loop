"""Attempts: one check run until it is decided: passed, red for good, timed out, or held by an editor lock and waited out."""
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from taskloop.adapters import check_files
from taskloop.app.checks.base import BaseCheck
from taskloop.app.checks.host import CheckHost
from taskloop.app.checks.keep import keep
from taskloop.app.checks.linux import LinuxRun
from taskloop.app.checks.step_env import step_env
from taskloop.contracts.argv import argv_of
from taskloop.contracts.checks import UNVERIFIED_EXIT, Check
from taskloop.contracts.enums import WaitWhat
from taskloop.contracts.envvars import EnvVar
from taskloop.domain.checks import matchers, retry

# the run's names that mean the same on the executor
REMOTE_ENV = frozenset({EnvVar.TL_RUN_ID.value, EnvVar.TL_ATTEMPT.value, EnvVar.TL_ARTIFACT_STEP.value})


@dataclass
class Outcome:
    rc: int
    tail: str  # the last lines of the last run's output
    seen: str  # all of its output
    tries: int
    secs: float  # of the last run
    base_red: bool = False
    wall_hit: bool = False  # stopped at the check's wall limit
    stopped: bool = False  # stopped by the flag it ran under (its lane was cancelled)


class Attempts:
    def __init__(self, host: CheckHost, base: BaseCheck, sleep: Callable[[float], None] = time.sleep) -> None:
        self.host, self.base, self.sleep = host, base, sleep

    def run(self, c: Check, log: Path, env: Mapping[str, str], stop: threading.Event | None = None) -> Outcome:
        """Run the check; a red one again when that can change the answer: only when the first two failures differ, never for a hang,
        a timeout or a compile error. `stop` set (the lane is cancelled): the run ends there, `stopped`, with no rerun and no base run."""
        tries, prior = 0, ""
        while True:
            tries += 1
            rc, tail, seen, took = self._once(c, log, env, stop)
            out = Outcome(rc, tail, seen, tries, took, wall_hit=self.host.wall_hit)
            if stop is not None and stop.is_set() and rc != 0 and self.host.killed:
                out.stopped = True
                return out
            if rc in {0, 124, UNVERIFIED_EXIT}:  # a rerun cannot make a check verify what the host lacks
                self._say_stop(c, out)
                return out
            sig = matchers.output_signature(seen)
            kind = matchers.failure_kind(seen, self.host.cfg.lock_fail)
            if kind == "lock":
                return self._wait_lock(c, log, env, out, stop)
            if tries == 1 and c.repo and self.base.red(c, stop):
                return Outcome(rc, tail, seen, tries, took, base_red=True, wall_hit=self.host.wall_hit)
            if not self._again(c, out, tries, sig, prior):
                return out
            prior = sig

    def _once(self, c: Check, log: Path, env: Mapping[str, str], stop: threading.Event | None) -> tuple[int, str, str, float]:
        t0 = time.time()
        rc, tail = self._exec(c, log, env, stop)
        seen = self._read(log, tail)
        took = time.time() - t0
        self.host.waits.note_slot_waits(seen, took)
        return rc, tail, seen, took

    def _exec(self, c: Check, log: Path, env: Mapping[str, str], stop: threading.Event | None) -> tuple[int, str]:
        """One run of the check on the host: its argv, its log, its kept files."""
        ids = {**step_env(self.host, c.id), EnvVar.TL_ARTIFACT_STEP.value: c.id}  # a new attempt directory for every run, a lock rerun too
        # what the repo's check declares in its `env` (it is part of the cache key: it must reach the child too)
        env = {**c.env, **env, **ids}
        argv = [*argv_of(c.cmd), *c.files]
        try:
            if c.where == "linux":
                rc, tail = self._linux(c, argv, env, ids, log, stop)
            else:
                rc, tail = self.host.sh(argv, timeout=c.wall_min * 60, save=log, what="check", env=env, stop=stop)
        except OSError as error:
            rc = 127 if isinstance(error, FileNotFoundError) else 126
            tail = f"check `{c.id}` could not start `{argv[0]}`: {error}"
            log.write_text(tail + "\n", encoding="utf-8")
        # before a retry, the next check or the slot's reset overwrites what this attempt left
        keep(self.host, c, log, Path(ids[EnvVar.TL_ARTIFACT_DIR.value]))
        return rc, tail

    def _linux(self, c: Check, argv: list[str], env: Mapping[str, str], ids: Mapping[str, str], log: Path,
               stop: threading.Event | None) -> tuple[int, str]:
        """The committed HEAD of the checkout this check runs in, on the executor: only what the check was told by its profile and
        the run's names go over (the local paths mean nothing there)."""
        wt, git = str(self.host.wt), self.host.git
        slot = Path(wt).name if c.run_in == "slot" else "clean"
        told = {k: v for k, v in env.items() if k in c.env or k in REMOTE_ENV}
        done = LinuxRun(self.host.cfg.executor, git, self.host.spawner).run(
            wt=wt, repo=check_files.repo_key(git, wt), slot=slot, sha=git.rev_parse(wt, "HEAD"), run_id=self.host.run_id,
            step=c.id, argv=argv, env=told, log=log, artifact_dir=Path(ids[EnvVar.TL_ARTIFACT_DIR.value]),
            timeout_s=c.wall_min * 60, stop=stop)
        self.host.killed, self.host.wall_hit = done.stopped or done.wall_hit, done.wall_hit  # what host.sh says of a stopped command
        return done.rc, done.tail

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
        if matchers.failure_kind(out.seen, self.host.cfg.lock_fail) == "deterministic":  # a rerun fails the same way, seconds later
            if c.retry:
                self.host.warn(f"`{c.id}` failed (exit {out.rc}) with a compile error: not retried")
            return False
        if not retry.retry_allowed(c.retry, tries, out.seen, self.host.cfg.lock_fail):
            return False
        if prior and sig == prior:
            self.host.warn(f"`{c.id}` failed twice with the same output: not retried")
            return False
        self.host.warn(f"`{c.id}` failed (exit {out.rc}), retrying: it is marked flaky")
        return True

    def _wait_lock(self, c: Check, log: Path, env: Mapping[str, str], out: Outcome, stop: threading.Event | None) -> Outcome:
        """An editor or project lock: wait, then rerun, 15/30/60 s up to 5 min in all."""
        rc, tail, seen = out.rc, out.tail, out.seen
        started = time.time() - out.secs
        for n, wait in enumerate(retry.lock_waits(), 1):
            self.host.warn(f"`{c.id}` is held by an editor or project lock; waiting {wait} s ({n})")
            wid = self.host.waits.start(WaitWhat.EDITOR_LOCK)
            if stop is None:
                self.sleep(wait)
            elif stop.wait(wait):  # the lane was cancelled while it waited
                return Outcome(rc, tail, seen, out.tries, out.secs, stopped=True)
            self.host.waits.add(wait, WaitWhat.EDITOR_LOCK, wid)
            rc, tail = self._exec(c, log, env, stop)
            seen = self._read(log, tail)
            self.host.waits.note_slot_waits(seen, time.time() - started)
            if rc == 0 or matchers.failure_kind(seen, self.host.cfg.lock_fail) != "lock":
                break
        if rc and matchers.failure_kind(seen, self.host.cfg.lock_fail) == "lock":
            tail += f"\n(still locked after {retry.LOCK_WAIT_MAX} s of waiting)"
        return Outcome(rc, tail, seen, out.tries, out.secs, wall_hit=self.host.wall_hit,
                       stopped=stop is not None and stop.is_set() and self.host.killed and rc != 0)
