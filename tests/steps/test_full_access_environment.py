"""Full-access launch and scratch lifecycle through real file ports, with semantic Git, process and agent fakes."""

import json
from dataclasses import replace
from pathlib import Path

from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome
from any_agent.access import CodexSandbox
from doubles import Command
from git_porcelain.testing import FakeWorktree
from test_environment import ENTRY, KEY, Entry
from test_environment import entry as environment_entry
from test_environment import environment as attempt_environment
from test_environment import implementing as implement_attempt

from taskloop.access import folders
from taskloop.agents.launch import AgentLaunch
from taskloop.agents.settings import CodexPolicy, encode_policy
from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Verified
from taskloop.environment import Preparation
from taskloop.evidence_files import EvidenceFiles
from taskloop.ids import NativeIds
from taskloop.slot_env import RealEnvFiles
from taskloop.slot_lock import custody, hold
from taskloop.slot_release import NotReleased, Released, SlotRelease
from taskloop.verifier import Verifier


def test_full_access_scratch_exists_at_dispatch_and_is_emptied_after_stopped_release(
    entry: Entry, slot: FakeWorktree,
) -> None:
    env, files = entry.environment, RealEnvFiles()
    env.con.execute("UPDATE attempt SET access_policy=?", (encode_policy(CodexPolicy(sandbox=CodexSandbox.DANGER_FULL_ACCESS)),))
    found = folders(slot.path)
    sibling = folders(slot.path.parent / "s2").tmp
    sibling.mkdir(parents=True)
    (sibling / "keep").write_text("another slot's scratch")

    def setup() -> None:
        assert all(path.is_dir() for path in found.roots)
        assert list(found.tmp.iterdir()) == []
        (found.tmp / "setup-scratch").write_text("setup")

    def agent(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        setting = next(arg for arg in spec.argv if arg.startswith("shell_environment_policy.set.TMPDIR="))
        scratch = Path(json.loads(setting.split("=", 1)[1]))
        assert scratch == found.tmp and scratch.is_dir() and list(scratch.iterdir()) == []
        (scratch / "agent-scratch").write_text("agent")
        return entry.agent(harness, spec, timeout, hooks)

    env.process.script = [Command(effect=setup)]
    preparation = Preparation(replace(env.preparation().ports, files=files, tmp_bytes=4096))
    store = AttemptStore(lambda: env.con)
    attempts = Attempts(store, EvidenceFiles(env.artifacts),
                        AgentLaunch(lambda _harness: ("/bin/codex", {"HOME": "/home/p"}), ids=NativeIds()),
                        agent, env.clock, entry.checkouts, entry.files, environment=preparation)
    result = attempts.execute(KEY, ENTRY, entry.renew)
    assert result.execution is not None and result.execution.answer.kind == "valid"
    assert env.probes == [] and "UV_OFFLINE" not in env.process.calls[0].env
    assert (found.tmp / "agent-scratch").read_text() == "agent"
    assert isinstance(Verifier(store, entry.checkouts, entry.files, lambda _worker: True, env.clock, hold,
                               ids=NativeIds()).verify(KEY), Verified)
    releaser = SlotRelease(store, entry.checkouts, entry.files, lambda _entry: "gone", lambda _worker: True,
                           custody, lambda _root, _task: True, env.clock, env.observe, files.empty_scratch, ids=NativeIds())
    refused = replace(releaser, gone=lambda _worker: False).release(KEY, False)
    assert isinstance(refused, NotReleased) and refused.reason == "worker_alive"
    assert (found.tmp / "agent-scratch").exists()
    assert env.con.execute("SELECT count(*) FROM reservation").fetchone() == (1,)
    assert isinstance(releaser.release(KEY, False), Released)
    assert found.tmp.is_dir() and list(found.tmp.iterdir()) == []
    assert env.con.execute("SELECT count(*) FROM reservation").fetchone() == (0,)
    assert (sibling / "keep").read_text() == "another slot's scratch"


# Reuse the implement-attempt and agent fixtures with conftest's physical tmp_path slot root.
implementing = implement_attempt
environment = attempt_environment
entry = environment_entry
