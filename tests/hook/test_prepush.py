"""The stdlib hook forwards the whole request and refuses an unavailable judge."""
import io
import subprocess
import sys
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.hook import main, prepush


class PushClient(Case):
    request = "refs/heads/a aaa refs/heads/a bbb\nrefs/heads/b ccc refs/heads/b ddd\n"

    def ask(self, result):
        top = subprocess.CompletedProcess([], 0, "/repo\n", "")
        with (mock.patch.object(prepush.subprocess, "run", side_effect=[top, result]) as run,
              redirect_stderr(io.StringIO())):
            rc = prepush.entry(["/bin/tl", "origin", "url"], self.request, {"TL_LAND": "1"})
        return rc, run

    def test_all_tips_are_forwarded_once_even_with_the_old_marker(self):
        rc, run = self.ask(subprocess.CompletedProcess([], 0, "", ""))
        assert rc == 0
        assert run.call_count == 2
        assert run.call_args.args[0] == ["/bin/tl", "judge-push", "--repo", "/repo"]
        assert run.call_args.kwargs["input"] == self.request

    def test_every_nonzero_judge_result_refuses(self):
        for code in (1, 2, 127, -9):
            with self.subTest(code=code):
                assert self.ask(subprocess.CompletedProcess([], code, "", "unavailable"))[0] != 0

    def test_a_missing_erroring_or_timed_out_judge_refuses(self):
        for error in (FileNotFoundError("tl"), ValueError("bad argv"), subprocess.TimeoutExpired("tl", 1),
                      RuntimeError("unexpected judge failure"), AttributeError("invalid answer")):
            with self.subTest(error=error):
                assert self.ask(error)[0] != 0

    def test_an_unparsable_judge_answer_refuses(self):
        assert self.ask(object())[0] != 0

    def test_judge_invocation_has_a_finite_timeout(self):
        _, run = self.ask(subprocess.CompletedProcess([], 0))
        assert run.call_args.kwargs["timeout"] > 0

    def test_missing_command_or_failed_repo_discovery_refuses(self):
        with redirect_stderr(io.StringIO()):
            assert prepush.entry([], self.request, {}) != 0
            for result in (subprocess.CompletedProcess([], 128, "/repo", "failed"),
                           subprocess.CompletedProcess([], 0, "", "")):
                with mock.patch.object(prepush.subprocess, "run", return_value=result) as run:
                    assert prepush.entry(["tl"], self.request, {}) != 0
                    assert run.call_count == 1

    def test_a_failed_chained_pre_push_hook_refuses(self):
        with (mock.patch.object(prepush, "entry", return_value=0),
              mock.patch.object(prepush, "original_hooks_dir", side_effect=OSError("unreadable")),
              redirect_stderr(io.StringIO())):
            assert prepush.githook("pre-push", ["tl"], self.request, {"TL_LAND": "1"}) != 0

    def test_the_repos_own_pre_push_hook_runs_read_only(self):
        with (mock.patch.object(prepush, "entry", return_value=0),
              mock.patch.object(prepush, "original_hooks_dir", return_value="/h"),
              mock.patch.object(prepush, "os_executable", return_value=True),
              mock.patch.object(prepush.Path, "is_file", return_value=True),
              mock.patch.object(prepush.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run):
            assert prepush.githook("pre-push", ["tl"], self.request, {"A": "b"}) == 0
        assert "env" not in run.call_args.kwargs

    def test_dispatcher_refuses_unexpected_pre_push_errors(self):
        stderr = io.StringIO()
        with (mock.patch.object(main.importlib, "import_module", side_effect=RuntimeError("judge failed")),
              redirect_stderr(stderr)):
            assert main.main(["githook", "pre-push", "tl"], self.request, Path("/plugin"), {}) != 0
        assert "judge failed" in stderr.getvalue()

    def test_unexpected_chained_hook_errors_refuse(self):
        with (mock.patch.object(prepush, "entry", return_value=0),
              mock.patch.object(prepush, "original_hooks_dir", side_effect=RuntimeError("unexpected")),
              redirect_stderr(io.StringIO())):
            assert prepush.githook("pre-push", ["tl"], self.request, {}) != 0

    def test_dispatcher_preserves_pretool_error_behavior(self):
        with mock.patch.object(main.importlib, "import_module", side_effect=RuntimeError("hook failed")):
            assert main.main(["pretool"], "{}", Path("/plugin"), {}) == 0

    def test_fail_mode_table_closes_only_pre_push(self):
        assert main.fail_exit(["githook", "pre-push", "tl"]) == main.FAIL_CLOSED
        for argv in (["pretool"], ["session-start"], ["precompact"], ["githook", "post-rewrite", "tl"], ["githook", "pre-commit"], []):
            assert main.fail_exit(argv) == main.FAIL_OPEN

    def test_unimportable_prepush_module_refuses(self):
        stderr = io.StringIO()
        with (mock.patch.object(main.importlib, "import_module", side_effect=ModuleNotFoundError("taskloop.hook.prepush")),
              redirect_stderr(stderr)):
            assert main.main(["githook", "pre-push", "tl"], self.request, Path("/plugin"), {}) == 1
        assert "prepush" in stderr.getvalue()


class JudgedByTheEngineInstall(Case):
    def test_the_engine_install_judges_not_the_shim(self):
        tl = Path(__file__)  # any existing file stands for the engine's tl.py
        assert prepush.judge_command("/shim/tl", {prepush.JUDGE_TL: str(tl)})[-2:] == ["--script", str(tl)]
        for environ in ({}, {prepush.JUDGE_TL: "/gone/tl.py"}, {prepush.JUDGE_TL: ""}):
            assert prepush.judge_command("/shim/tl", environ) == ["/shim/tl"]

    def test_entry_runs_the_engine_install(self):
        tl = Path(__file__)
        result = subprocess.CompletedProcess([], 0)
        top = subprocess.CompletedProcess([], 0, stdout="/repo\n")
        with mock.patch.object(prepush.subprocess, "run", side_effect=[top, result]) as run:
            assert prepush.entry(["/shim/tl", "origin", "url"], "refs", {prepush.JUDGE_TL: str(tl)}) == 0
        assert run.call_args_list[1].args[0][-4:-2] == [str(tl), "judge-push"]
