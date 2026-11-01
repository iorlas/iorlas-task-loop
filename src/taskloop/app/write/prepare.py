"""Coordinator prerequisites: a successful stamp belongs to this run and these input contents."""
import hashlib
import json
from pathlib import Path
from typing import Protocol

from taskloop.app.checks.host import CheckHost
from taskloop.app.write.state import StageState
from taskloop.contracts.paths import RunFiles
from taskloop.domain.checks.inputs import matching
from taskloop.domain.checks.matchers import expand_braces

PREPARED = "prepared"


class PrepareHost(CheckHost, Protocol):
    def blocked_for(self, why: str, kind: str) -> Exception: ...


class Prepare:
    def __init__(self, host: PrepareHost) -> None:
        self.e = host

    def inputs(self) -> tuple[str, int]:
        """Hash tracked contents and globbed files: deletions and preserved mtimes still invalidate."""
        e, cfg = self.e, self.e.cfg.prepare
        if cfg is None:
            return "", 0
        wt = Path(e.wt)
        paths = {p for pattern in cfg.inputs for g in expand_braces(pattern) for p in wt.glob(g) if p.is_file()}
        paths.update(wt / p for p in matching(e.git.ls_files(str(wt)), cfg.inputs))
        digest = hashlib.sha256(json.dumps([cfg.cmd, cfg.inputs]).encode())
        newest = 0
        for path in sorted(paths):
            digest.update(str(path.relative_to(wt)).encode() + b"\0")
            if path.is_file():
                digest.update(hashlib.sha256(path.read_bytes()).digest())
                newest = max(newest, path.stat().st_mtime_ns)
            else:
                digest.update(b"deleted")
        return digest.hexdigest(), newest

    def run(self, *, force: bool = False) -> bool:
        """Run outside the writer's sandbox. Failure preserves both output tails without a successful stamp."""
        e, cfg = self.e, self.e.cfg.prepare
        if cfg is None:
            return False
        stamp = RunFiles(e.run_dir).prepare_stamp()
        try:
            fingerprint, newest = self.inputs()
            if not force and stamp.exists() and stamp.read_text() == fingerprint and newest <= stamp.stat().st_mtime_ns:
                return False
            stamp.unlink(missing_ok=True)
            ran = e.spawner.run(cfg.cmd, cwd=str(e.wt), extra=e.bead_env, timeout_s=cfg.timeout_min * 60)
            tail = "stdout:\n" + ran.out[-4000:] + "\nstderr:\n" + ran.err[-4000:]
            status = "timed out" if ran.timed_out else f"exit {ran.exit}"
            e.log.note(f"engine.prepare {status}\n{tail}")
            if ran.exit or ran.timed_out:
                raise e.blocked_for(f"failed: engine.prepare {status}\n{tail}", "FAULT_INFRA")
            fingerprint, _ = self.inputs()
            stamp.write_text(fingerprint)
            return True
        except OSError as err:
            raise e.blocked_for(f"failed: engine.prepare: {err}", "FAULT_INFRA") from err

    def retry(self, s: StageState, text: str) -> bool:
        """One prerequisite repair per logical write round; it spends neither a write attempt nor a replan."""
        cfg = self.e.cfg.prepare
        if cfg is None or s.prepare_retried or not any(t.casefold() in text.casefold() for t in cfg.triggers if t):
            return False
        self.run(force=True)
        s.prepare_retried = True
        s.feedback = "The coordinator ran engine.prepare successfully. Retry this write with refreshed prerequisites.\n" + s.feedback
        return True
