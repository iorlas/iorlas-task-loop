"""The lifecycle of a standalone stage verb, using the engine's manifests and logs."""
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from taskloop.contracts import log as rec
from taskloop.contracts.enums import Outcome
from taskloop.contracts.identity import Identity
from taskloop.contracts.locator import RunBundle, RunLocator, host_name
from taskloop.contracts.run import RunState
from taskloop.contracts.runlife import BEAT_EVERY
from taskloop.stores.bundle import Stores
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import RunLog


@dataclass
class StageRun:
    bundle: RunBundle
    log: RunLog
    stores: Stores
    rc: int = 1


@contextmanager
def stage_run(who: Identity, repo: str, mode: str) -> Generator[StageRun]:
    """Open before doing work; keep evidence and record a terminal state on every exit, including exceptions."""
    locator = RunLocator(who.config)
    bundle = locator.create(repo, "", time.time(), mode=mode, owner=who.actor, session=who.session)
    stopped = threading.Event()
    helper: threading.Thread | None = None
    rc, reason = 1, "stage interrupted"
    try:
        stores = real_stores(who.config)
        log = RunLog(stores.run_log(bundle.run), run_id=bundle.run, host=host_name())
        stage = StageRun(bundle, log, stores)
        locator.beat(bundle.run, time.time())

        def heartbeat() -> None:
            while not stopped.wait(BEAT_EVERY):
                locator.beat(bundle.run, time.time())

        helper = threading.Thread(target=heartbeat, daemon=True)
        helper.start()
        log.emit(rec.RunStart(worktree=repo, mode=mode, owner=who.actor, session=who.session))
        try:
            yield stage
        except BaseException as exc:
            reason = str(exc) or type(exc).__name__
            log.warn(reason)
            raise
        else:
            rc, reason = stage.rc, "" if stage.rc == 0 else f"exit {stage.rc}"
        finally:
            log.emit(rec.Close(outcome=Outcome.DONE if rc == 0 else Outcome.FAILED, why=reason))
    except BaseException:
        rc = 1
        raise
    finally:
        stopped.set()
        if helper is not None and helper.ident is not None:
            helper.join()
        locator.end(bundle.run, time.time(), RunState.DONE if rc == 0 else RunState.FAILED, reason)
