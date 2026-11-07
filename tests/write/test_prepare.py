"""Prerequisites run in the coordinator and repair stale assets without spending a write or replan."""
import os
from pathlib import Path
from unittest import mock

import pytest
from support import procsim
from support.engine_case import EngineTest

from taskloop.app.pipeline.blocked import Blocked
from taskloop.app.write.prepare import Prepare
from taskloop.app.write.state import StageState
from tlkernel import rundocs
from tlkernel.kinds import Kind
from tlkernel.procport import Ran
from tltestkit.cfgs import plan_of
from tltestkit.logs import records
from tltestkit.narrow import must
from tltestkit.plans import CLEAN, PLAN, RED_ONCE, WRITE


class PrepareTests(EngineTest):
    def command(self, events):
        def run(cwd, env):
            events.append("prepare")
            return 0, "restored packages"
        return [procsim.fake("prepare-deps", run)]

    def test_prepare_precedes_first_write_and_unchanged_inputs_skip_later_writes(self):
        self.put_repo_file("App.csproj", "unchanged")
        events = []

        def write(script, node, cwd, resume):
            events.append("write")
            return WRITE

        rc, _ = self.run_engine({"plan": [PLAN], "write": [write, write], "review": [CLEAN]},
                                prepare={"cmd": self.command(events), "inputs": ["**/*.csproj"]},
                                checks=[{"id": "red-once", "cmd": RED_ONCE}])
        assert rc == 0
        assert events == ["prepare", "write", "write"]

    def test_changed_input_is_prepared_before_the_next_write(self):
        self.put_repo_file("packages.lock.json", "old")
        events = []

        def write(script, node, cwd, resume):
            events.append("write")
            Path(cwd, "packages.lock.json").write_text("new")
            return WRITE

        rc, _ = self.run_engine({"plan": [PLAN], "write": [write, write], "review": [CLEAN]},
                                prepare={"cmd": self.command(events), "inputs": ["packages.lock.json"]},
                                checks=[{"id": "red-once", "cmd": RED_ONCE}])
        assert rc == 0
        assert events == ["prepare", "write", "prepare", "write"]

    def test_restore_claim_retries_same_write_without_a_replan_or_attempt(self):
        events = []
        claim = dict(WRITE, bad_checks=[{"cmd": "has-f", "why": "Coordinator must run DOTNET RESTORE: project.assets.json stale"}])
        rc, script = self.run_engine({"plan": [PLAN], "write": [claim, WRITE], "review": [CLEAN]},
                                     prepare={"cmd": self.command(events), "triggers": ["restore", "NU1"]}, max_replans=0)
        assert rc == 0
        assert events == ["prepare", "prepare"]
        assert script.nodes.count("write") == 2
        assert self.eng.state.replans == 0
        assert self.eng.stats["writes"] == 1
        assert [r["write"] for r in self.eng.write.write_rounds] == [1, 1]

    def test_check_assets_failure_prepares_and_retries_without_consuming_counters(self):
        events = []

        def check(cwd, env):
            return (0, "ok") if len(events) == 2 else (1, "NU1101: missing assets")

        cmd = procsim.fake("assets-check", check)
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN]},
                                prepare={"cmd": self.command(events), "triggers": ["restore", "NU1"]}, max_replans=0,
                                max_check_tries=1, max_rounds=1, checks=[{"id": "assets", "cmd": cmd}])
        assert rc == 0
        assert events == ["prepare", "prepare"]
        assert (self.eng.state.replans, self.eng.stats["writes"], self.eng.stats["rounds"]) == (0, 1, 0)

    def test_failed_prepare_keeps_both_output_tails_and_no_stamp(self):
        eng = self.checks_engine(prepare={"cmd": ["restore"], "timeout_min": 12})
        with (
            mock.patch.object(eng.spawner, "run", return_value=Ran(exit=7, out="package details", err="network unavailable")) as run,
            pytest.raises(Blocked) as stopped,
        ):
            Prepare(eng).run()
        assert stopped.value.kind == Kind.FAULT_INFRA
        assert "exit 7" in stopped.value.why
        assert "package details" in stopped.value.why
        assert "network unavailable" in stopped.value.why
        assert rundocs.prepare_stamp(eng.home, eng.run_id).get() is None
        assert any("network unavailable" in r["text"] for r in records(eng, "note"))
        run.assert_called_once_with(["restore"], cwd=str(eng.wt), extra=eng.bead_env, timeout_s=720)

    def test_failed_prepare_stops_the_engine_before_any_writer_starts(self):
        cmd = procsim.fake("failed-prepare", lambda cwd, env: (1, "package feed unavailable"))
        rc, script = self.run_engine({"plan": [PLAN]}, prepare={"cmd": [cmd]})
        assert rc == 2
        assert self.eng.kind == Kind.FAULT_INFRA
        assert "write" not in script.nodes
        assert self.eng.stats["writes"] == 0
        assert "package feed unavailable" in self.eng.why

    def test_timeout_is_an_infrastructure_failure_with_its_output(self):
        eng = self.checks_engine(prepare={"cmd": ["restore"]})
        with (
            mock.patch.object(eng.spawner, "run", return_value=Ran(exit=124, out="restoring", timed_out=True)),
            pytest.raises(Blocked) as stopped,
        ):
            Prepare(eng).run()
        assert "timed out" in stopped.value.why
        assert "restoring" in stopped.value.why
        assert rundocs.prepare_stamp(eng.home, eng.run_id).get() is None

    def test_custom_triggers_replace_defaults_and_repair_is_bounded(self):
        eng = self.checks_engine(prepare={"cmd": ["restore"], "triggers": ["fetch-deps"]})
        s = StageState(plan_of(PLAN), 0, None)
        prepare = Prepare(eng)
        with mock.patch.object(eng.spawner, "run", return_value=Ran(exit=0)) as run:
            assert not prepare.retry(s, "please restore project.assets.json")
            assert prepare.retry(s, "please FETCH-DEPS")
            assert not prepare.retry(s, "please FETCH-DEPS again")
        run.assert_called_once()

    def test_newer_mtime_and_content_change_with_preserved_mtime_each_invalidate(self):
        path = self.wt / "packages.lock.json"
        path.write_text("old")
        eng = self.checks_engine(prepare={"cmd": ["restore"], "inputs": ["packages.lock.json"]})
        prepare = Prepare(eng)
        with mock.patch.object(eng.spawner, "run", return_value=Ran(exit=0)) as run:
            assert prepare.run()
            assert not prepare.run()
            stamp_time = must(rundocs.prepare_stamp(eng.home, eng.run_id).get()).ns
            os.utime(path, ns=(stamp_time + 1, stamp_time + 1))
            assert prepare.run()
            old_time = path.stat().st_mtime_ns
            path.write_text("new")
            os.utime(path, ns=(old_time, old_time))
            assert prepare.run()
        assert run.call_count == 3
