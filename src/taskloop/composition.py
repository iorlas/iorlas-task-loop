"""Construct the factory's operations over the real boundaries: per-thread shared writers on factory.db (sqlite_store),
real Git views (`git_views`), the slot file port (`slot_files`), owned-process observations (`owned_processes`), the
tracker client (`tracker_client`), the agent run and wall clock."""

import shutil
import sqlite3
import sys
import time
from pathlib import Path

from any_agent import run
from sqlite_store import Store
from stream_proc import group_alive, observe_owned, popen_registered

from taskloop import slot_lock
from taskloop.admit import AttemptAdmission
from taskloop.admit_chain import ChainAdmission, NextAdmission
from taskloop.agent_credentials import codex_machine_credentials
from taskloop.attempt import Attempts, Credentials
from taskloop.attempt_reads import AttemptReads
from taskloop.attempt_store import REGISTRATION_BUSY_MS, AttemptStore
from taskloop.environment import EnvironmentPorts, Preparation
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import checkouts, remotes, slot_profiles
from taskloop.launch import Launcher
from taskloop.owned_processes import entry_seen, setup_seen, worker_gone
from taskloop.publish import BranchPublish
from taskloop.setup_store import SetupStore
from taskloop.slot_env import RealEnvFiles, sandbox_probe, setup_process
from taskloop.slot_files import RealSlotFiles
from taskloop.slot_release import SlotRelease
from taskloop.slots import Adopted, NotAdopted, SlotGit, adopt
from taskloop.tracker_client import inspect_tracker_task, tracker_claims
from taskloop.verifier import Verifier


def open_attempts(database: Path, artifacts: Path, credentials: Credentials = codex_machine_credentials) -> Attempts:
    """Real wiring: released run, per-thread shared writers on factory.db, wall-clock deadlines.

    The harness registration write goes through its own store, whose connections wait at most REGISTRATION_BUSY_MS for the
    write lock; every other write keeps the library's 5 s.
    """
    store, registration = Store(SCHEMA), Store(SCHEMA)

    def bounded() -> sqlite3.Connection | None:
        con = registration.shared_rw(database)
        if con is not None:
            con.execute(f"PRAGMA busy_timeout={REGISTRATION_BUSY_MS}")
        return con

    evidence = EvidenceFiles(artifacts)
    setup = SetupStore(lambda: store.shared_rw(database), store.begin_immediate, AttemptReads(bounded, registration.begin_immediate))
    ports = EnvironmentPorts(
        setup, checkouts, slot_profiles, RealEnvFiles(), setup_process, setup_seen,
        group_alive, evidence, time.time, sys.platform, shutil.rmtree.avoids_symlink_attacks, sandbox_probe,
        (artifacts.absolute(), database.absolute().parent),
    )
    return Attempts(
        AttemptStore(lambda: store.shared_rw(database), store.begin_immediate),
        evidence,
        credentials,
        run,
        time.time,
        checkouts,
        RealSlotFiles(),
        registration_store=AttemptStore(bounded, registration.begin_immediate),
        environment=Preparation(ports),
    )


def real_slots() -> SlotGit:
    """Real Git views and the real slot file port: how a slot is observed and adopted."""
    return SlotGit(checkouts, RealSlotFiles())


def open_verifier(database: Path, store: Store) -> Verifier:
    """Real wiring for on-demand verification (`tl step verify`, a repeat's verify): a shared writer of `store` (the caller
    closes it) on factory.db, real Git, wall clock, its Git writes under the slot's custody lock."""
    writer = AttemptStore(lambda: store.shared_rw(database), store.begin_immediate)
    return Verifier(writer, checkouts, RealSlotFiles(), worker_gone, time.time, slot_lock.hold)


def open_releaser(database: Path, store: Store) -> SlotRelease:
    """Real wiring for `tl step release` and the release after `tl step verify`: a shared writer of `store` (the caller
    closes it) on factory.db, real Git, the entry and worker observations, the park under the slot's custody lock, the
    tracker's fenced unclaim, wall clock."""
    writer = AttemptStore(lambda: store.shared_rw(database), store.begin_immediate)
    return SlotRelease(writer, checkouts, RealSlotFiles(), entry_seen, worker_gone, slot_lock.custody, tracker_claims().unclaim, time.time,
                       setup_seen, RealEnvFiles().empty_scratch)


def open_publisher(database: Path, store: Store) -> BranchPublish:
    """Real wiring for `tl step publish` and the publication after `tl step verify`: a shared writer of `store` (the caller
    closes it) on factory.db, the remote-capable Git view, the real slot file port, wall clock."""
    return BranchPublish(AttemptStore(lambda: store.shared_rw(database), store.begin_immediate), remotes, RealSlotFiles(), time.time)


def open_launcher(database: Path, artifacts: Path) -> Launcher:
    """Real wiring: the released registered start and owned-process observation, this interpreter, wall-clock deadlines.

    The database path is made absolute here: the entry refuses a relative one, after its registration would commit."""
    return Launcher(database.absolute(), EvidenceFiles(artifacts), time.time, popen_registered, observe_owned, sys.executable)


def adopt_slots(
    database: Path, checkout: Path, root: Path, count: int, git: SlotGit | None = None
) -> tuple[Adopted | NotAdopted, ...]:
    """Adopt worktrees a person already made with `git worktree add --detach <root>/<repo_id>/sN`; creates none. `git`
    defaults to real Git and the real slot file port (`real_slots`)."""
    store, git = Store(SCHEMA), git or real_slots()
    try:
        repo = git.checkouts(checkout.expanduser().resolve())
        return adopt(lambda: store.shared_rw(database), store.begin_immediate, repo, git, root, count)
    finally:
        store.close_shared()


def open_admission(database: Path, artifacts: Path) -> AttemptAdmission:
    """Real wiring: per-thread shared writers on factory.db, the tracker claim, the real Git boundary, wall-clock deadlines."""
    store = Store(SCHEMA)
    claims = tracker_claims()
    return AttemptAdmission(
        lambda: store.shared_rw(database),
        store.begin_immediate,
        EvidenceFiles(artifacts),
        inspect_tracker_task,
        checkouts,
        claims.claim,
        claims.unclaim,
        time.time,
        slot_lock.probe,
        RealSlotFiles(),
    )


def open_chain(database: Path, artifacts: Path) -> ChainAdmission:
    """Real wiring of the admissions that continue a task: per-thread shared writers on factory.db, wall-clock deadlines."""
    store = Store(SCHEMA)
    return ChainAdmission(lambda: store.shared_rw(database), store.begin_immediate, EvidenceFiles(artifacts), time.time)


def open_advance(database: Path, artifacts: Path) -> NextAdmission:
    """Real wiring of a step's advance: per-thread shared writers on factory.db, the task read (status and assignee),
    the real Git boundary and slot lock probe, wall-clock deadlines; no claim."""
    store = Store(SCHEMA)
    return NextAdmission(
        lambda: store.shared_rw(database), store.begin_immediate, EvidenceFiles(artifacts), inspect_tracker_task, checkouts, time.time,
        slot_lock.probe, RealSlotFiles(),
    )
