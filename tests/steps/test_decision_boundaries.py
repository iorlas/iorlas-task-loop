"""Ordinary admission and execution need no optional skill or managed hook installation."""

import json
import os
import sqlite3
from pathlib import Path

import pytest
from any_agent import RunOutcome, Summary
from any_agent.testing import FakeRun
from git_porcelain.testing import FakeRepo
from test_admit import ENTRY, PLAN, WORKER, admit, attempts, slots

from taskloop.admit import Admitted
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Checkouts, SlotFiles


def test_normal_work_needs_no_skill_or_managed_hook_installation(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path,
    checkouts: Checkouts, slot_files: SlotFiles, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "environ", {})
    slots(factory, repo, root, 1)
    admitted = admit(factory, tmp_path, repo)
    assert isinstance(admitted, Admitted)
    assert AttemptStore(lambda: factory).register_entry(admitted.key, ENTRY, 10) == "accepted"
    run = FakeRun(RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(PLAN), rc=0, stands=True)))
    result = attempts(factory, tmp_path, run, checkouts, slot_files).execute(admitted.key, ENTRY)
    assert (result.status, result.reason) == ("pending", "verification")
    assert len(run.calls) == 1
    assert not list(tmp_path.rglob(".agents")) and not list(tmp_path.rglob(".claude"))
    assert not list(tmp_path.rglob("hooks"))
