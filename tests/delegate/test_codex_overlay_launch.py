"""The real delegate launch uses and removes the overlay; workers are local fakes, never a login or model call."""

import json
import os
import sys
from pathlib import Path
from unittest import mock

from delegate.app import env, launch
from support.procsim import real_proc

from run_support import RunBase


class WiredOverlay(RunBase):
    def setup_method(self):
        super().setup_method()
        (env.config_dir() / "host.json").write_text(
            json.dumps({"binaries": {"python": sys.executable}, "writer_exec_allow": [["python", "-m", "unittest"]]})
        )
        self.flag = ["--writer-exec-allow", '[["python","-m","unittest"]]']

    @real_proc("delegate: a worker, git or CLI process")
    def test_writer_receives_overlay_and_it_is_removed_after_the_call(self):
        code, result = self.run_it(*self.flag)
        assert (code, result["stop"]) == (0, None)
        environment = dict(line.split("=", 1) for line in Path(os.environ["FAKE_ENV"]).read_text().splitlines() if "=" in line)
        overlay = Path(environment["CODEX_HOME"])
        assert environment["CODEX_HOME"] != os.environ["CODEX_HOME"]
        assert not overlay.exists()
        assert "--ignore-rules" not in self.args_seen()
        assert "approval_policy=never" in self.args_seen()
        assert "--exec-allow" in Path(os.environ["FAKE_ARGS"] + ".brief").read_text()
        assert launch.ESCALATE_RULE not in Path(os.environ["FAKE_ARGS"] + ".brief").read_text()

    @real_proc("delegate: a worker, git or CLI process")
    def test_empty_list_preserves_original_environment_flags_and_prompt(self):
        code, result = self.run_it("--writer-exec-allow", "[]")
        assert (code, result["stop"]) == (0, None)
        assert "--ignore-rules" in self.args_seen()
        assert "approval_policy=on-request" in self.args_seen()
        assert "--exec-allow" not in Path(os.environ["FAKE_ARGS"] + ".brief").read_text()
        assert launch.ESCALATE_RULE in Path(os.environ["FAKE_ARGS"] + ".brief").read_text()
        assert not list(env.config_dir().glob("codex-exec-*"))

    @real_proc("delegate: a worker, git or CLI process")
    def test_cleanup_on_launch_failure(self):
        roots = []

        def fail(supervisor, spec, timeout):
            root = Path(spec.env["CODEX_HOME"])
            assert (root / "rules/default.rules").is_file()
            roots.append(root)
            raise OSError("fake launch error")

        with mock.patch.object(launch.Supervisor, "run", fail):
            _, result = self.run_it(*self.flag)
        assert result["stop"]["reason"] == "crash"
        assert roots
        assert all(not root.exists() for root in roots)

    @real_proc("delegate: a worker, git or CLI process")
    def test_read_step_and_non_codex_kind_refuse_the_grant(self):
        for role, flags in (("reviewer", []), ("worker", ["--only-family", "claude"])):
            with self.subTest(role=role, flags=flags):
                _, result = self.run_it(*self.flag, *flags, role=role)
                assert result["stop"]["reason"] == "bad_request"
                assert not list(env.config_dir().glob("codex-exec-*"))

    @real_proc("delegate: a worker, git or CLI process")
    def test_resume_gets_its_own_overlay_and_rules(self):
        self.run_it()
        _, result = self.run_it(*self.flag, "--resume", "thread-123")
        assert result["stop"] is None
        assert "exec resume" in self.args_seen()
        assert "approval_policy=never" in self.args_seen()
        assert not list(env.config_dir().glob("codex-exec-*"))
