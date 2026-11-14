"""Conflict handoff wiring shares the ordinary land's stores, environment and adapter lifetimes."""

import os
import threading
from functools import partial
from pathlib import Path

from git_porcelain import Repo

from taskloop.agent_credentials import machine_credentials
from taskloop.agents.launch import AgentLaunch, CredentialsUnavailable, probe_for
from taskloop.attempt_loads import AttemptLoads
from taskloop.claim_lease import HeartbeatFor, KeepAlive, keeping, renewal
from taskloop.composition import Checking, _run
from taskloop.git_views import GitProfileFiles, GitViews
from taskloop.ids import NativeIds
from taskloop.land_check import LandPorts
from taskloop.land_conflict.admit import Ports as AdmissionPorts
from taskloop.land_conflict.execute import Ports as ExecutionPorts
from taskloop.land_conflict.execute import execute
from taskloop.land_conflict.handoff import Handoff
from taskloop.land_conflict.models import Record
from taskloop.land_conflict.store import ConflictStore
from taskloop.land_store import LandStore
from taskloop.merge.models import Reason, Result, Unavailable
from taskloop.merge.store import MergeStore
from taskloop.owned_processes import this_process, worker_gone
from taskloop.slot_lock import landing, probe
from taskloop.slots import SlotGit
from taskloop.tracker_client import inspect_tracker_task, tracker_claims


def conflict_handoff(work: Checking, views: GitViews, heartbeat_for: HeartbeatFor) -> Handoff:
    store = ConflictStore(work.store.connect, work.store.begin)
    attempts = AttemptLoads(work.store.connect, work.store.begin)
    merges = MergeStore(work.store.connect, work.store.begin)

    def admission(repo: Repo) -> AdmissionPorts:
        return AdmissionPorts(store, attempts, work.files, repo, SlotGit(work.checkouts, work.slot_files),
                              probe, work.clock, work.ids)

    def execution(repo: Repo, record: Record) -> Result:
        try:
            credentials = machine_credentials(record.inputs.setting.harness)
        except CredentialsUnavailable as error:
            return Unavailable(reason=Reason.UNKNOWN, explanation=str(error))
        alive = KeepAlive(heartbeat_for(record.request.tracker_root, record.request.task_id), threading.Event(), work.clock)
        ports = ExecutionPorts(store, merges, repo, work.checkouts, views.remotes, work.slot_files, work.files,
            AgentLaunch(machine_credentials, ids=work.ids), _run, worker_gone, work.clock, work.preparation,
            renewal(alive), credentials, probe_for(record.inputs.setting, Path(record.slot_path), credentials[0]))
        with keeping(alive):
            return execute(ports, record.key)

    return Handoff(store, admission, execution)


def land_ports(work: Checking, views: GitViews) -> LandPorts:
    claims = tracker_claims()
    return LandPorts(work, LandStore(work.store.connect, work.store.begin), views.remotes,
        partial(GitProfileFiles, repos=views.remotes), inspect_tracker_task, claims.heartbeat_for,
        threading.Event, this_process, probe, landing, os.environ, claims.close,
        conflict_handoff(work, views, claims.heartbeat_for), ids=NativeIds())
