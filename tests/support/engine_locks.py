"""An engine lock written from plain fields (contracts/locks.py EngineLock), for tests that plant one."""
from pathlib import Path
from typing import Any

from support import homes
from taskloop.app.slots import engine_lock
from taskloop.contracts.locks import EngineLock


def put_lock(wt: str | Path, f: dict[str, Any]) -> None:
    engine_lock.write_engine_lock(homes.cfg(), wt, EngineLock(
        pid=f["pid"], start=f.get("start", ""), bead=f.get("bead", ""), slot=f.get("slot", ""), slot_bead=f.get("slot_bead", ""),
        by=f.get("by", "run-task"), started=float(f.get("started", 1.0))))
