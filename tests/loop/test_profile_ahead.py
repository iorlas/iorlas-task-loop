"""A profile update belongs to the installation: no bead failure, held slot or crash."""
import contextlib
import json
import sys
from os import EX_CONFIG
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from slots.test_slot_pool import ME, Rig
from support.fake_loop_env import slot_loop_env

from taskloop.app.loop import verdict as vd
from taskloop.app.loop.files import EXIT_REASONS
from taskloop.app.loop.loop import Loop, LoopArgs
from taskloop.app.loop.run import Where
from taskloop.app.loop.stages import EngineSlots
from taskloop.contracts import wire
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import ConfigError, ProfileReadError, RepoProfile
from taskloop.contracts.enums import Result
from taskloop.contracts.ids import BeadId
from taskloop.contracts.parks import ParkStore
from taskloop.contracts.run import RunReport
from taskloop.domain.lanes import pauses


class ProfileAhead(Rig):
    def unreadable(self):
        return ProfileReadError("/repo/.task-loop.json", "abc123", ValueError("bad JSON"))

    def test_unreadable_run_log_parks_with_the_original_diagnostic(self):
        error = self.unreadable()
        path = Path(self.d1) / "absent.json"
        log = Path(self.d1) / "run.log"
        with mock.patch.object(Path, "read_text", side_effect=[FileNotFoundError(), f"task-loop: {error}\n"]):
            verdict, gave = vd.read(path, EX_CONFIG, log, "test")
        assert not gave
        assert (verdict.outcome, verdict.kind) == (Result.PAUSED, vd.PROFILE_AHEAD)
        assert verdict.why == str(error)
        assert "newer than" not in verdict.why

    def test_unreadable_profile_at_startup_and_refresh_preserves_diagnostic(self):
        for startup in (True, False):
            with self.subTest(startup=startup):
                loop = self.make_loop()
                error = self.unreadable()
                self.loop_env.fetch = mock.Mock()
                self.loop_env.profile = mock.Mock(side_effect=error)
                if startup:
                    loop = Loop(self.loop_env, self.files, mock.Mock(), LoopArgs())
                with mock.patch.object(loop, "prune"), mock.patch.object(loop, "run", side_effect=loop.refresh):
                    assert loop.main() == EX_CONFIG
                record = self.files.write_exit.call_args.args[0]
                assert record["reason"] == vd.PROFILE_AHEAD
                assert record["detail"] == str(error)

    def test_config_exit_preserves_read_error_cause_but_unknown_fields_keep_newer_wording(self):
        error = self.unreadable()
        exited = SystemExit(EX_CONFIG)
        exited.__cause__ = error
        assert vd.profile_ahead("test", exited).why == str(error)
        assert "profile newer than this tl" in vd.profile_ahead("test", ConfigError("unknown field")).why

    def test_unreadable_profile_during_preparation_parks_without_bead_failure(self):
        loop = self.make_loop()
        bid = BeadId("x-1")
        bead = Bead(id=bid, title="work", status="in_progress", assignee=ME, labels=["keep"])
        self.bd.beads[bid] = bead
        self.loop_env.claim = mock.Mock(return_value=(True, ""))
        error = self.unreadable()
        with mock.patch.object(loop.taker, "prepare", side_effect=error):
            taken = loop.taker.attempt_all(
                [bead], Where("s1", self.d1, None, self.t[0]), True, loop.prof.engine, mock.Mock(), mock.Mock())
        assert taken.verdict is not None
        assert taken.verdict.why == str(error)
        assert (self.bd.beads[bid].status, self.bd.beads[bid].labels) == ("open", ["keep"])
        park = ParkStore(self.env.cfgdir).get(bid)
        assert park is not None
        assert (park.permanence, park.retry_at) == ("needs_owner", 0)

    def make_loop(self):
        self.loop_env = slot_loop_env(self.env)
        self.loop_env.profile = lambda: RepoProfile(slots=self.env.cfg)
        self.files = mock.Mock()
        self.files.runs.return_value = Path(self.d1)
        self.files.lock = contextlib.nullcontext
        self.files.stop_for.return_value = ""
        return Loop(self.loop_env, self.files, mock.Mock(), LoopArgs())

    def test_missing_outcome_exit_config_is_an_owner_pause_and_other_exits_still_fail(self):
        path = Path(self.d1) / "absent.json"
        for code in (EX_CONFIG, 1, 0, None):
            with self.subTest(code=code):
                verdict, gave = vd.read(path, code, path, "0.23.test")
                assert not gave
                if code == EX_CONFIG:
                    assert (verdict.outcome, verdict.kind) == (Result.PAUSED, "profile_ahead")
                    assert "tl 0.23.test; restart the factory on the installed version" in verdict.why
                    policy = pauses.rule(verdict.kind)
                    assert (policy.permanence, policy.base_s, policy.cap_s) == ("needs_owner", 0, 0)
                else:
                    assert verdict.outcome == Result.FAILED

    def test_an_outcome_file_takes_precedence_over_exit_config(self):
        path = Path(self.d1) / "outcome.json"
        path.write_text(json.dumps(wire.dump(RunReport(outcome=Result.LANDED, bead=BeadId("x-1")))))
        verdict, gave = vd.read(path, EX_CONFIG, path, "test")
        assert gave
        assert verdict.outcome == Result.LANDED

    def test_invalid_outcome_is_still_a_failure_even_with_exit_config(self):
        path = Path(self.d1) / "invalid.json"
        path.write_text("{}")
        verdict, gave = vd.read(path, EX_CONFIG, path, "test")
        assert not gave
        assert verdict.outcome == Result.FAILED
        assert "not a RunReport" in verdict.why

    def test_run_config_exit_releases_bead_and_slot_and_stops_without_failure_or_timer(self):
        loop = self.make_loop()
        bid = BeadId("x-1")
        bead = Bead(id=bid, title="work", status="in_progress", assignee=ME, labels=["keep"])
        self.bd.beads[bid] = bead
        slot_bead = self.slot().take_locked("loop")
        child = mock.Mock(pid=321)
        child.wait.return_value = EX_CONFIG

        def spawn(*args):
            self.loop_env.profile = mock.Mock(side_effect=SystemExit(EX_CONFIG))
            assert isinstance(self.loop_env.slots, EngineSlots)
            self.loop_env.slots.slot_env = mock.Mock(side_effect=SystemExit(EX_CONFIG))
            return child, mock.Mock()

        self.loop_env.spawn = spawn
        self.loop_env.run_task_argv = mock.Mock(return_value=[])
        self.loop_env.claim = mock.Mock(return_value=(True, ""))
        self.loop_env.loop_lock = mock.Mock()
        self.loop_env.drop_engine_lock = mock.Mock()
        with (
            mock.patch.object(loop, "acquire", return_value=("s1", self.d1, slot_bead)),
            mock.patch.object(loop.taker, "prepare", return_value=None),
            mock.patch.object(self.loop_env.slots, "lease") as lease,
            mock.patch.object(loop, "prune"),
            mock.patch.object(loop, "run", side_effect=lambda: loop.work([bead], mock.Mock())),
        ):
            assert loop.main() == EX_CONFIG
        lease.return_value.start.return_value.stop.assert_called_once()
        assert (self.bd.beads[bid].status, self.bd.beads[bid].assignee) == ("open", "")
        assert self.bd.beads[bid].labels == ["keep"]
        assert self.bd.beads[slot_bead].status == "open"
        assert (loop.c.ran, loop.c.fails, loop.c.pauses, loop.c.later) == (0, [], {}, {})
        park = ParkStore(self.env.cfgdir).get(bid)
        assert park is not None
        assert (park.reason, park.permanence, park.retry_at) == ("profile_ahead", "needs_owner", 0)
        assert self.files.write_exit.call_args.args[0]["reason"] == "profile_ahead"
        assert "profile_ahead" in EXIT_REASONS
        self.files.rest_bead.assert_not_called()

    def test_profile_error_during_slot_preparation_reopens_the_claimed_bead(self):
        loop = self.make_loop()
        bid = BeadId("x-1")
        bead = Bead(id=bid, title="work", status="in_progress", assignee=ME)
        self.bd.beads[bid] = bead
        self.loop_env.claim = mock.Mock(return_value=(True, ""))
        with mock.patch.object(loop.taker, "prepare", side_effect=SystemExit(EX_CONFIG)):
            taken = loop.taker.attempt_all(
                [bead], Where("s1", self.d1, None, self.t[0]), True, loop.prof.engine, mock.Mock(), mock.Mock())
        assert taken.verdict is not None
        assert taken.verdict.kind == "profile_ahead"
        assert (self.bd.beads[bid].status, self.bd.beads[bid].assignee) == ("open", "")
        park = ParkStore(self.env.cfgdir).get(bid)
        assert park is not None
        assert (park.permanence, park.retry_at) == ("needs_owner", 0)

    def test_initial_profile_error_records_clean_exit_without_starting_work(self):
        for error in (SystemExit(EX_CONFIG), ConfigError("unknown field")):
            self.make_loop()
            self.loop_env.profile = mock.Mock(side_effect=error)
            loop = Loop(self.loop_env, self.files, mock.Mock(), LoopArgs())
            with mock.patch.object(loop, "run") as run:
                assert loop.main() == EX_CONFIG
            run.assert_not_called()
            assert self.files.write_exit.call_args.args[0]["reason"] == "profile_ahead"

    def test_profile_refresh_error_records_clean_exit_without_fallback(self):
        for error in (SystemExit(EX_CONFIG), ConfigError("unknown field")):
            loop = self.make_loop()
            self.loop_env.fetch = mock.Mock()
            self.loop_env.profile = mock.Mock(side_effect=error)
            with (
                mock.patch.object(loop, "prune"),
                mock.patch.object(loop, "run", side_effect=loop.refresh),
                mock.patch.object(loop, "fall_back") as fallback,
            ):
                assert loop.main() == EX_CONFIG
            fallback.assert_not_called()
            record = self.files.write_exit.call_args.args[0]
            assert record["reason"] == "profile_ahead"
            assert record["detail"] == vd.profile_ahead(self.loop_env.version).why

    def test_other_system_exits_are_not_reported_as_profile_errors(self):
        loop = self.make_loop()
        with (
            mock.patch.object(loop, "prune"),
            mock.patch.object(loop, "run", side_effect=SystemExit(1)),
            pytest.raises(SystemExit) as exited,
        ):
            loop.main()
        assert exited.value.code == 1
        assert self.files.write_exit.call_args.args[0]["reason"] == "system_exit"
