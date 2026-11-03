"""Detached factory supervision; no OS service and no automatic restart after reboot."""
import contextlib
import hashlib
import os
import time
from collections.abc import Callable
from pathlib import Path

from taskloop.adapters import pidcheck
from taskloop.adapters.locks import hold_path
from taskloop.app.asks import raiser
from taskloop.app.launch import factory
from taskloop.app.loop.files import LoopFiles
from taskloop.contracts.ask import FACTORY_NOTICE_RUN, AskDetail, AskOption
from taskloop.contracts.enums import AskClass, AskStatus, LockWhat
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import Spawner
from taskloop.contracts.stores import AskStore
from taskloop.domain.asks.spec import AskSpec


def enabled(files: LoopFiles) -> Path:
    return files.runs() / "factory.enabled"


def alive(files: LoopFiles) -> bool:
    try:
        pid, start = (files.runs() / "supervisor.pid").read_text().splitlines()
        return pidcheck.proc_alive(int(pid), start)
    except (OSError, ValueError):
        return False


def alert(files: LoopFiles, repo: str, why: str) -> None:
    """One soft owner-inbox notification per outage, without creating a work bead."""
    bead = BeadId("factory-" + hashlib.sha1(files.key.encode()).hexdigest()[:12])
    asks = AskStore.at(files.cfg)
    old = asks.get(bead)
    if old is not None and old.status in (AskStatus.OPEN, AskStatus.PARKED) and old.answer is None:
        return
    spec = AskSpec(
        AskClass.OPEN_QUESTION, "The factory is down; can you restart it on the host?",
        tried=["The detached supervisor attempted to restore the factory"],
        options=[AskOption(label="I restarted it", consequence="Record your acknowledgement of the manual restart.",
                           text="I ran tl factory start on the host.", recommended=True),
                 AskOption(label="Keep retrying", consequence="The live supervisor continues its restart probes.",
                           text="Keep retrying while the supervisor is alive.")],
        detail=AskDetail(text=f"{repo}: {why}\nRun tl factory start --repo {repo} on the host; do this manually after a reboot."),
        blocking=False, default="Retry while the supervisor lives; after reboot, manually run tl factory start.")
    raiser.raise_ask(asks, spec, raiser.Asking(bead=bead, run=FACTORY_NOTICE_RUN, brief_hash="", repo=repo,
                                            title="Factory down", now=files.now(), why=why))


def recovered(files: LoopFiles) -> None:
    bead = BeadId("factory-" + hashlib.sha1(files.key.encode()).hexdigest()[:12])
    asks = AskStore.at(files.cfg)
    old = asks.get(bead)
    if old is not None and old.status in (AskStatus.OPEN, AskStatus.PARKED):
        asks.withdraw(bead, old.id, "Factory lanes restored", files.now())


def ensure(files: LoopFiles, repo: str, argv: list[str], spawner: Spawner, lanes: int) -> None:
    """Idempotent launch reservation uses the same lock as lane start and stop."""
    with files.lock():
        enabled(files).write_text(str(lanes))
        if alive(files):
            return
        with (files.runs() / "supervisor.log").open("ab") as out:
            child = spawner.start(argv, cwd=repo, stdin="null", out=out, extra={"PYTHONUNBUFFERED": "1"})
        (files.runs() / "supervisor.pid").write_text(f"{child.pid}\n{pidcheck.proc_start(child.pid)}\n")


def disable(files: LoopFiles) -> None:
    with files.lock():
        enabled(files).unlink(missing_ok=True)


def run(files: LoopFiles, repo: str, version: str, argv: list[str], spawner: Spawner,
        sleep: Callable[[float], None] = time.sleep) -> int:
    """Top up every ten seconds, including after startup failures; graceful stop disables restarts first."""
    with hold_path(files.runs() / "supervisor.lock", f"pid {os.getpid()}", what=LockWhat.LOOP):
        while enabled(files).exists():
            try:
                lanes = max(1, int(enabled(files).read_text()))
                states, _added = factory.start(files, repo, version, argv, spawner, lanes=lanes, enabled=enabled(files))
                if len(states) >= lanes and all(st.actor for st in states):
                    recovered(files)
            except (OSError, RuntimeError, ValueError) as error:
                with contextlib.suppress(OSError, ValueError):
                    alert(files, repo, str(error))
                print(f"factory supervisor: {error}", flush=True)
            sleep(10)
    return 0
