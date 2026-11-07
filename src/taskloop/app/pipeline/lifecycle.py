"""Run liveness and close-out, independent of the run body and lease implementation."""
import contextlib
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from tlkernel import fence
from tlkernel.beadsport import Beads
from tlkernel.checkpoint import Checkpoint
from tlkernel.enums import Step
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.locator import RunLocator
from tlkernel.log import Beat
from tlkernel.paths import ConfigDir
from tlkernel.plancheck import PlanData
from tlkernel.run import RunState

from taskloop.adapters.deadline import DeadlineExpired, deadline
from taskloop.app.pipeline import ended as stored_end
from taskloop.app.pipeline import requests
from taskloop.app.pipeline.blocked import Blocked
from taskloop.app.pipeline.crash import CrashHost, parked_crash
from taskloop.app.pipeline.finish import outcome as finished_outcome
from taskloop.app.pipeline.finish import terminal_state
from taskloop.app.pipeline.ports import Reexecs
from taskloop.app.pipeline.reload import Exec
from taskloop.domain import outcome as oc


class LeaseLike(Protocol):
    def start(self) -> object: ...
    def stop(self) -> None: ...


class LifecycleCheckpoints(Protocol):
    def read(self) -> Checkpoint | None: ...


class LifecycleConfig(Protocol):
    @property
    def run_deadline_min(self) -> float: ...


class LifecycleRequests(Protocol):
    @property
    def stopped(self) -> bool: ...
    def drop(self) -> None: ...
    def at_beat(self) -> None: ...


class LifecycleRecords(Protocol):
    def heartbeat(self) -> None: ...
    def settle(self, state: RunState, reason: str) -> None: ...
    def finish(self, done: oc.RunOutcome) -> oc.RunOutcome: ...


class LifecycleStuck(Protocol):
    def tick(self) -> None: ...


class LifecycleResume(Protocol):
    def restore(self, ck: Checkpoint, *, late: bool = False) -> None: ...


class LifecycleCloser(Protocol):
    def close(self, done: oc.RunOutcome) -> None: ...
    def pause(self, done: oc.RunOutcome) -> None: ...


class LifecycleReload(Protocol):
    def save_net_pause(self) -> None: ...


class LifecycleSteps(Protocol):
    def end(self) -> None: ...


class LifecycleLog(Protocol):
    def warn(self, text: str) -> object: ...
    def emit(self, record: Beat, /) -> object: ...


class LifecycleHost(CrashHost, Protocol):
    prev_ck: str
    fenced: str
    plan_data: PlanData | None
    plan_summary: str
    accepted: list[int]
    branch: str

    @property
    def store(self) -> Beads: ...
    @property
    def bead(self) -> BeadId: ...
    @property
    def checkpoints(self) -> LifecycleCheckpoints: ...
    @property
    def dead(self) -> Checkpoint | None: ...
    @property
    def cfg(self) -> LifecycleConfig: ...
    @property
    def requests(self) -> LifecycleRequests: ...
    @property
    def log(self) -> LifecycleLog: ...
    @property
    def records(self) -> LifecycleRecords: ...
    @property
    def stuck(self) -> LifecycleStuck: ...
    @property
    def moved(self) -> bool: ...
    @property
    def resume(self) -> LifecycleResume: ...
    @property
    def landed_sha(self) -> str: ...
    @property
    def claim(self) -> fence.Claim: ...
    @property
    def closer(self) -> LifecycleCloser: ...
    @property
    def reload(self) -> LifecycleReload: ...
    @property
    def steps(self) -> LifecycleSteps: ...
    @property
    def home(self) -> ConfigDir: ...
    @property
    def run_id(self) -> str: ...
    @property
    def dry(self) -> bool: ...
    def stop_deferred(self) -> contextlib.AbstractContextManager[None]: ...
    def warn(self, text: str) -> object: ...


@dataclass
class Ended:
    """The outcome carried from the body through close-out."""
    outcome: oc.RunOutcome = field(default_factory=lambda: oc.make(Kind.FAULT_ENGINE))


class Lifecycle:
    def __init__(self, host: LifecycleHost, *, body: Callable[[LeaseLike, Ended], None],
                 lease: Callable[[Callable[[], None], Callable[[BaseException], None]], LeaseLike], reexecs: Reexecs) -> None:
        self.host = host
        self.body = body
        self.lease = lease
        self.reexecs = reexecs

    def go(self) -> int:
        host = self.host
        end = Ended()
        hb = self.lease(self.beat, self.beat_died)
        ck = host.checkpoints.read()
        host.prev_ck = ck.run if ck else ""
        try:
            if host.dead is not None:  # the last run died inside its close: this process only finishes it
                self.finish_dead(end)
            else:
                with deadline(host.cfg.run_deadline_min * 60, "run"):
                    self.body(hb, end)
        except DeadlineExpired as err:
            end.outcome = oc.make(Kind.OWNER_PARK, f"{err}; branch and checkpoint kept")
        except Blocked as b:
            end.outcome = b.outcome
            if b.kind is Kind.PAUSE_KILLED and host.requests.stopped:  # the stop flag was the owner's request, not a SIGTERM
                end.outcome = oc.make(b.kind, requests.STOPPED_WHY)
        except fence.Fenced as f:  # the bead or the slot was taken again: this run writes nothing more
            host.fenced = f.why
            end.outcome = oc.make(Kind.FAULT_ENGINE, f.why)
        except Exec:
            pass  # the process image is gone; nothing below runs in a real exec
        except Exception as err:  # the close-out must run whatever broke
            host.log.warn("engine error\n" + "".join(traceback.format_exception(err)))
            end.outcome = oc.make(Kind.FAULT_ENGINE, f"failed: engine error {type(err).__name__}: {err}")
        finally:
            self.close_out(hb, end)
        return 0 if host.moved or end.outcome.finished else 2

    def finish_dead(self, end: Ended) -> None:
        """The state the close's effects read comes back from the dead run's checkpoint; the outcome is the one it kept."""
        host = self.host
        ck = host.dead
        assert ck is not None and ck.ended is not None
        end.outcome, _, _ = stored_end.loaded(ck.ended.outcome)
        host.resume.restore(ck, late=True)
        host.plan_data = ck.state.plan_data
        host.plan_summary = (host.plan_data or {}).get("summary", "")
        host.accepted = list(ck.state.accepted)
        host.branch = ck.branch

    def beat(self) -> None:
        """The run's heartbeat in its manifest (its state is running, alive as of now) and a Beat in its log (the stuck rule's tick), then
        the stuck tick and the owner's stop; a file that cannot be written must not kill the beat thread."""
        self.host.records.heartbeat()
        with contextlib.suppress(OSError):
            self.host.log.emit(Beat())
        self.host.stuck.tick()
        self.host.requests.at_beat()

    def beat_died(self, err: BaseException) -> None:
        """The heartbeat thread ended on an error: the run goes on without a beat, so the log says so before the lease lapses."""
        self.host.log.warn("the heartbeat thread died, the lease will lapse: " + "".join(traceback.format_exception(err)))

    def close_out(self, hb: LeaseLike, end: Ended) -> None:
        """The close, then the run's one terminal state, whatever the close did (a close that raises still leaves a state)."""
        try:
            self.close(hb, end)
        except fence.Fenced as err:
            self.host.fenced = err.why
            raise
        except Blocked:
            raise
        except Exception as err:
            self.failed_close(err, end)
        finally:
            self.settle(end)

    def failed_close(self, err: Exception, end: Ended) -> None:
        host = self.host
        bundle = RunLocator(host.home).get(host.run_id)
        if bundle is not None and bundle.manifest.finish is not None:
            host.warn("close failed after the run's answer was recorded; keeping it\n" + "".join(traceback.format_exception(err)))
            end.outcome = host.records.finish(finished_outcome(bundle.manifest.finish))
        else:
            end.outcome = parked_crash(host, Step.CLOSE, err)
            host.closer.pause(end.outcome)
            host.steps.end()
            end.outcome = host.records.finish(end.outcome)

    def settle(self, end: Ended) -> None:
        host = self.host
        if host.moved:  # exec'd into a newer install: the same run goes on, the next process takes it up
            return
        if host.fenced:
            host.records.settle(RunState.STOPPED, f"fenced out: {host.fenced}")
        else:
            host.records.settle(terminal_state(end.outcome), end.outcome.detail or end.outcome.kind.name)

    def close(self, hb: LeaseLike, end: Ended) -> None:
        host = self.host
        if host.moved:
            hb.stop()
            return
        with host.stop_deferred():  # a stop here would skip the close: no trace, no bead update
            if host.landed_sha and end.outcome.kind not in (Kind.LANDED, Kind.ENGINE_CRASH, Kind.PAUSE_NETWORK):
                # Late crashes and bd sync outages keep their retry cursor after the push went through.
                host.warn(f"{end.outcome.detail or end.outcome.word} after the land went through; closing it landed")
                end.outcome = oc.make(Kind.LANDED, sha=host.landed_sha)
            hb.stop()
            host.fenced = host.fenced or fence.stale(host.store, host.claim)
            if host.fenced:  # a run that lost its lease closes nothing: the bead, its checkpoint and its trace are the new holder's
                host.warn(f"fenced out: {host.fenced}; the bead, its checkpoint and the slot are left to the run that holds them")
                return
            host.stuck.tick()  # the last tick: a run that stops on its third same red says it before its Close
            host.requests.drop()  # what the run did not take is for a run that ended
            self.reexecs.drop(host.bead)  # a run that ended is no crash after an exec
            if end.outcome.kind is Kind.PAUSE_NETWORK and not host.dry:
                host.reload.save_net_pause()
            host.why = end.outcome.detail
            host.closer.close(end.outcome)
            bundle = RunLocator(host.home).get(host.run_id)
            if bundle is not None and bundle.manifest.finish is not None:
                end.outcome = finished_outcome(bundle.manifest.finish)
