"""A check with `in: linux` never runs on this machine: with no executor it is a red result and the host shell is not called."""

from unittest import mock

from tlkernel import check_files
from tlkernel.checks import Check
from tlkernel.config import ExecutorConfig
from tlkernel.ids import CheckId

from tlgate.attempts import Attempts
from tlgate.linux import EXECUTOR_DOWN_RC, Remote


def test_without_an_executor_the_check_fails_loudly_and_does_not_run_here(workdir):
    host = mock.Mock()
    host.wt, host.run_dir, host.run_id = workdir, workdir, "r1"
    host.cfg.executor = ExecutorConfig()
    host.git.rev_parse.return_value = "abc"
    host.git.common_dir.return_value = ""
    host.git.config_get.return_value = "https://example.com/repo.git"
    host.spawner = mock.Mock()
    log = workdir / "log"
    with mock.patch("tlgate.attempts.step_env", return_value={"TL_ARTIFACT_DIR": str(workdir)}):
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
    with (
        mock.patch("tlgate.attempts.step_env", return_value={"TL_ARTIFACT_DIR": str(workdir)}),
        mock.patch("tlgate.attempts.LinuxRun") as linux,
    ):
        linux.return_value.run.return_value = done
        rc, _ = Attempts(host, mock.Mock())._exec(Check(id=CheckId("t"), cmd="true", where="linux"), workdir / "log", {}, None)
    assert (rc, host.killed, host.wall_hit) == (-15, True, False)


def _route(workdir, folder, origin, run_in="slot"):
    root = workdir / "repo"
    dot = root / ".git"
    dot.mkdir(parents=True, exist_ok=True)
    (dot / "config").write_text(f'[remote "origin"]\nurl = {origin}\n' if origin else "")
    host = mock.Mock()
    host.wt, host.run_dir, host.run_id = workdir / folder, workdir, "r1"
    host.git.common_dir.return_value = str(dot)
    host.git.rev_parse.return_value = "abc"
    check = Check(id=CheckId("t"), cmd="true", where="linux", run_in=run_in)
    with mock.patch("tlgate.attempts.LinuxRun") as linux:
        linux.return_value.run.return_value = Remote(0, "")
        Attempts(host, mock.Mock())._linux(check, ["true"], {}, {"TL_ARTIFACT_DIR": str(workdir)}, workdir / "log", None)
    return linux.return_value.run.call_args.kwargs, host


def test_slot_route_mirrors_origin_and_worktree_folder(workdir):
    args, _ = _route(workdir, "slot-one", "git@example.com:owner/name.git")
    assert (args["repo"], args["slot"]) == ("owner/name", "slot-one")


def test_two_slots_share_repo_but_keep_their_names(workdir):
    first, _ = _route(workdir, "slot-one", "https://example.com/owner/name.git")
    second, _ = _route(workdir, "slot-two", "https://example.com/owner/name.git")
    assert first["repo"] == second["repo"] == "owner/name"
    assert (first["slot"], second["slot"]) == ("slot-one", "slot-two")


def test_clean_route_uses_clean_name(workdir):
    args, _ = _route(workdir, "slot-one", "https://example.com/owner/name.git", "clean")
    assert args["slot"] == "clean"


def test_no_origin_route_uses_repo_folder(workdir):
    args, _ = _route(workdir, "slot-one", "")
    assert args["repo"] == "repo"


def test_unsafe_origin_route_uses_cache_key(workdir):
    args, host = _route(workdir, "slot-one", "https://example.com/../name.git")
    assert args["repo"] == str(check_files.repo_key(host.git, str(host.wt)))
