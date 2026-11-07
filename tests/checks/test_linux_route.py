"""A check with `in: linux` never runs on this machine: with no executor it is a red result and the host shell is not called."""
from unittest import mock

from taskloop.app.checks.attempts import Attempts
from taskloop.app.checks.linux import EXECUTOR_DOWN_RC, Remote
from taskloop.contracts.checks import Check
from taskloop.contracts.config import ExecutorConfig
from taskloop.contracts.ids import CheckId


def test_without_an_executor_the_check_fails_loudly_and_does_not_run_here(workdir):
    host = mock.Mock()
    host.wt, host.run_dir, host.run_id = workdir, workdir, "r1"
    host.cfg.executor = ExecutorConfig()
    host.git.rev_parse.return_value = "abc"
    host.git.common_dir.return_value = ""
    host.git.config_get.return_value = "https://example.com/repo.git"
    host.spawner = mock.Mock()
    log = workdir / "log"
    with mock.patch("taskloop.app.checks.attempts.step_env", return_value={"TL_ARTIFACT_DIR": str(workdir)}):
        rc, tail = Attempts(host, mock.Mock())._exec(Check(id=CheckId("t"), cmd="true", where="linux"), log, {}, None)
    assert rc == EXECUTOR_DOWN_RC, Remote
    assert "executor" in tail and "is down" in tail
    host.sh.assert_not_called()
    host.spawner.run.assert_not_called()


def test_a_stopped_linux_check_is_reported_as_stopped_by_the_engine(workdir):
    host = mock.Mock()
    host.wt, host.run_dir, host.run_id = workdir, workdir, "r1"
    host.git.rev_parse.return_value = "abc"
    host.git.common_dir.return_value = ""
    host.git.config_get.return_value = "https://example.com/repo.git"
    done = Remote(rc=-15, tail="", stopped=True)
    with mock.patch("taskloop.app.checks.attempts.step_env", return_value={"TL_ARTIFACT_DIR": str(workdir)}), \
            mock.patch("taskloop.app.checks.attempts.LinuxRun") as linux:
        linux.return_value.run.return_value = done
        rc, _ = Attempts(host, mock.Mock())._exec(Check(id=CheckId("t"), cmd="true", where="linux"), workdir / "log", {}, None)
    assert (rc, host.killed, host.wall_hit) == (-15, True, False)
