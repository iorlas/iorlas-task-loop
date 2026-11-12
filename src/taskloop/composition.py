"""Construct the factory's operations over the real boundaries: per-thread shared writers on factory.db (sqlite_store),
real Git views (`git_views`), the slot file port (`slot_files`), owned-process observations (`owned_processes`), the
tracker client (`tracker_client`), the agent run and wall clock."""

import os
import shutil
import sqlite3
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, run
from sqlite_store import Store
from stream_proc import group_alive, observe_owned, popen_held, popen_registered, stop_tree

from taskloop import slot_lock
from taskloop.admit import AttemptAdmission
from taskloop.admit_chain import ChainAdmission, NextAdmission
from taskloop.agent_credentials import codex_machine_credentials, scrubbed
from taskloop.attempt import Attempts, Credentials
from taskloop.attempt_reads import AttemptReads, StoreConnection
from taskloop.attempt_store import REGISTRATION_BUSY_MS, AttemptStore
from taskloop.attempt_types import Checkouts, Observe, SlotFiles
from taskloop.check_admit import ChecksAdmission
from taskloop.check_release import ChecksRelease
from taskloop.check_store import CheckStore
from taskloop.checks import Block, BlockPorts
from taskloop.command_sink import WatchedHooks
from taskloop.environment import EnvironmentPorts, Preparation, SlotProfiles
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitProfileFiles, checkouts, remotes, slot_profiles
from taskloop.keep_awake import Helper, Host
from taskloop.launch import CHECK_ENTRY_MODULE, Launcher
from taskloop.owned_processes import entry_seen, setup_seen, worker_gone
from taskloop.publish import BranchPublish
from taskloop.setup_store import SetupSeen, SetupStore
from taskloop.slot_env import RealEnvFiles, sandbox_probe, setup_process
from taskloop.slot_files import RealSlotFiles
from taskloop.slot_release import Scratch, SlotRelease
from taskloop.slots import Adopted, NotAdopted, SlotGit, adopt
from taskloop.tracker_client import inspect_tracker_task, tracker_claims
from taskloop.verifier import Verifier


def _registration(database: Path) -> tuple[Store, Callable[[], sqlite3.Connection | None]]:
    """The registration store, whose connections wait at most REGISTRATION_BUSY_MS for the write lock (every other write
    keeps the library's 5 s), and its connection."""
    registration = Store(SCHEMA)

    def bounded() -> sqlite3.Connection | None:
        con = registration.shared_rw(database)
        if con is not None:
            con.execute(f"PRAGMA busy_timeout={REGISTRATION_BUSY_MS}")
        return con

    return registration, bounded


def _environment(setup: SetupStore, database: Path, artifacts: Path) -> Preparation:
    """The slot environment's real ports: real Git, files, the registered start, the process table and the probe."""
    return Preparation(EnvironmentPorts(
        setup, checkouts, slot_profiles, RealEnvFiles(), setup_process, setup_seen,
        group_alive, EvidenceFiles(artifacts), time.time, sys.platform, shutil.rmtree.avoids_symlink_attacks, sandbox_probe,
        (artifacts.absolute(), database.absolute().parent),
    ))


def _run(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
    """The shelf's `run`, with the live sink the attempt's hooks carry (`command_sink.WatchedHooks`)."""
    return run(harness, spec, timeout, hooks, live=hooks.live if isinstance(hooks, WatchedHooks) else None)


def open_attempts(database: Path, artifacts: Path, credentials: Credentials = codex_machine_credentials) -> Attempts:
    """Real wiring: released run, per-thread shared writers on factory.db, wall-clock deadlines.

    The harness registration write goes through its own store's bounded connections (`_registration`)."""
    store, (registration, bounded) = Store(SCHEMA), _registration(database)
    setup = SetupStore(lambda: store.shared_rw(database), store.begin_immediate, AttemptReads(bounded, registration.begin_immediate))
    return Attempts(
        AttemptStore(lambda: store.shared_rw(database), store.begin_immediate),
        EvidenceFiles(artifacts),
        credentials,
        _run,
        time.time,
        checkouts,
        RealSlotFiles(),
        registration_store=AttemptStore(bounded, registration.begin_immediate),
        environment=_environment(setup, database, artifacts),
    )


@dataclass(frozen=True)
class Checking:
    """What a checks attempt's entry (`check_entry`) works with: its store and its setup runs' store, its evidence, the
    Git views and slot file port, the profile port on a slot's pinned view, the slot environment (setup without a
    probe), the block, the process-table observations of a registered command and entry, the scratch's emptying, the
    clock and the scrubbed environment every setup and check command gets (`agent_credentials.scrubbed`, read when the
    slot is set up: a fault there is the entry's counted `fault:CredentialsUnavailable`)."""

    store: CheckStore
    setups: SetupStore
    files: EvidenceFiles
    checkouts: Checkouts
    slot_files: SlotFiles
    profiles: SlotProfiles
    preparation: Preparation
    block: Block
    seen: SetupSeen
    entry_seen: Observe
    scratch: Scratch
    clock: Callable[[], float]
    environ: Callable[[], Mapping[str, str]]


def open_checking(database: Path, artifacts: Path) -> Checking:
    """Real wiring of the checks entry: per-thread shared writers on factory.db (each command's identity through the
    bounded registration connections), real Git, files and processes, wall clock, this process's scrubbed environment."""
    store, (registration, bounded) = Store(SCHEMA), _registration(database)
    registering = StoreConnection(bounded, registration.begin_immediate)
    setup = SetupStore(lambda: store.shared_rw(database), store.begin_immediate, AttemptReads(bounded, registration.begin_immediate))
    return Checking(
        CheckStore(lambda: store.shared_rw(database), store.begin_immediate, registering), setup, EvidenceFiles(artifacts), checkouts,
        RealSlotFiles(), slot_profiles, _environment(setup, database, artifacts), Block(BlockPorts(setup_process, group_alive, time.time)),
        setup_seen, entry_seen, RealEnvFiles().empty_scratch, time.time, lambda: scrubbed(os.environ),
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


def open_checks_launcher(database: Path, artifacts: Path) -> Launcher:
    """`open_launcher` for checks attempts: `CheckStore`'s attempts and registration, the checks entry module."""
    return Launcher(database.absolute(), EvidenceFiles(artifacts), time.time, popen_registered, observe_owned, sys.executable,
                    CheckStore, CHECK_ENTRY_MODULE)


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


def open_checks_admission(database: Path) -> ChecksAdmission:
    """Real wiring of a checks attempt's admission (an advance to the check step, or a re-run): per-thread shared writers
    on factory.db, the task read, the real Git boundary and slot lock probe, the profile read on the person's checkout,
    wall-clock deadlines; no claim, no input file."""
    store = Store(SCHEMA)
    return ChecksAdmission(lambda: store.shared_rw(database), store.begin_immediate, inspect_tracker_task, checkouts, time.time,
                           slot_lock.probe, RealSlotFiles(), GitProfileFiles)


def open_checks_releaser(database: Path, store: Store) -> ChecksRelease:
    """Real wiring for `tl step release` of a checks attempt: a shared writer of `store` (the caller closes it) on
    factory.db, real Git, the entry and command observations, the reset and park under the slot's custody lock, wall clock;
    no tracker call."""
    writer = CheckStore(lambda: store.shared_rw(database), store.begin_immediate)
    return ChecksRelease(writer, checkouts, RealSlotFiles(), entry_seen, slot_lock.custody, time.time, setup_seen,
                         RealEnvFiles().empty_scratch)


def keep_awake_spawn(argv: Sequence[str]) -> Helper:
    """The keep-awake helper (`keep_awake`): in a session of its own (the terminal's Ctrl-C reaches only rounds), every
    stream on one `/dev/null` opened natively and closed after the spawn; the shelf's hold, replayed by the caller first
    inside the `try` that stops it (`stop_tree`). OSError when it cannot start (the hold already replayed then)."""
    with open(os.devnull, "r+b") as null:
        child, hold = popen_held(list(argv), stdin=null, stdout=null, stderr=null, start_new_session=True)
    return Helper(child.pid, hold.replay, lambda: stop_tree(child))


def keep_awake_host() -> Host:
    """This machine: `sys.platform`, PATH lookup, the real spawn."""
    return Host(sys.platform, shutil.which, keep_awake_spawn)
