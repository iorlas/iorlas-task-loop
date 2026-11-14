"""Retain checked inputs and reserve detached work without starting execution."""

from collections.abc import Callable
from dataclasses import dataclass

from git_porcelain import GitUnavailable, Repo

from taskloop.attempt_loads import AttemptLoads
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_types import AttemptKey
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.ids import Ids
from taskloop.land_conflict.models import AdmissionRefused, Outcome, Record, Request, Result
from taskloop.land_conflict.store import ConflictStore
from taskloop.slots import Probe, SlotGit

EXPLANATIONS = {
    Outcome.ADMITTED: "The checked conflict's inputs and slot reservation are retained for detached execution.",
    Outcome.RETAINED: "The existing conflict admission and its original inputs are retained.",
    Outcome.SOURCE: "The exact checked source identity or retained inputs no longer match.",
    Outcome.NOT_CHECKED: "The source needs its latest released, passed checks.",
    Outcome.NOT_DONE: "The implement attempt must be current with its released claim kept.",
    Outcome.LANDING: "Delivery work already holds this source; no conflict work was admitted.",
    Outcome.INPUT: "The original requirements artifact could not be validated; no work was admitted.",
    Outcome.NO_SLOT: "No observed free, clean, detached slot remains available.",
    Outcome.UNAVAILABLE: "Admission inputs or local execution state could not be read safely.",
}


@dataclass(frozen=True)
class Ports:
    store: ConflictStore
    attempts: AttemptLoads
    files: EvidenceFiles
    repo: Repo
    git: SlotGit
    probe: Probe
    clock: Callable[[], float]
    ids: Ids


def admit(ports: Ports, request: Request) -> Result:
    try:
        found = ports.store.find(request)
        if found is not None:
            return Result(outcome=Outcome.RETAINED, explanation=EXPLANATIONS[Outcome.RETAINED], record=found)
        inputs = ports.attempts.retained(request.source)
        if inputs is None or not request.matches(inputs) or ports.repo.identity().key != request.repo_id:
            raise AdmissionRefused(Outcome.SOURCE)
        ports.files.read(inputs.input_ref)
        slots = ports.store.observe(ports.repo, ports.git, request, ports.probe)
        if not slots:
            raise AdmissionRefused(Outcome.NO_SLOT)
        first = slots[0]
        proposed = Record(key=AttemptKey(ports.ids.hex(), ports.ids.token(16), first.generation + 1), request=request,
                          inputs=inputs, slot=first.name, slot_path=first.path, base=first.head, admitted_at=ports.clock())
        record, created = ports.store.insert(proposed, slots)
        outcome = Outcome.ADMITTED if created else Outcome.RETAINED
        return Result(outcome=outcome, explanation=EXPLANATIONS[outcome], record=record)
    except EvidenceError:
        outcome = Outcome.INPUT
    except (AdmissionRefused, StoreRefused) as error:
        outcome = error.outcome if isinstance(error, AdmissionRefused) else Outcome(error.reason)
        if outcome is Outcome.NO_SLOT:
            try:
                found = ports.store.find(request)
            except AdmissionRefused as changed:
                outcome, found = changed.outcome, None
            except (StoreUnavailable, ValueError):
                outcome = Outcome.UNAVAILABLE
                found = None
            if found is not None:
                return Result(outcome=Outcome.RETAINED, explanation=EXPLANATIONS[Outcome.RETAINED], record=found)
    except (StoreUnavailable, GitUnavailable, ValueError):
        outcome = Outcome.UNAVAILABLE
    return Result(outcome=outcome, explanation=EXPLANATIONS[outcome])
