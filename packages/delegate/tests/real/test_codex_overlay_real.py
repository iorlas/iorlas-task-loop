"""UNITYCODEX: per-call rules grant only a guard invocation, never a raw executable."""

import ast
import json
import os
import subprocess
import sys

from any_agent.protocol import LaunchSpec

from delegate.app import codex_policy, env
from tltestkit.case import Case
from tltestkit.procsim import real_proc


def rules_at(home):
    """Parse just the generated prefix_rule syntax; no eval or real agent/login."""
    result = []
    for line in (home / "rules/default.rules").read_text().splitlines():
        call = ast.parse(line).body[0].value
        assert call.func.id == "prefix_rule"
        result.append({kw.arg: ast.literal_eval(kw.value) for kw in call.keywords})
    return result


class Overlay(Case):
    def setup_method(self):
        self.root = env.config_dir()
        self.policy = {
            "binaries": {"python": sys.executable, "just": "/opt/just"},
            "writer_exec_allow": [["python", "-m", "unittest"], ["python", "-m", "pytest"], ["just", "check"]],
        }
        (self.root / "host.json").write_text(json.dumps(self.policy))
        self.spec = LaunchSpec(
            argv=[
                "codex",
                "exec",
                "--ignore-rules",
                "--ignore-user-config",
                "-c",
                "approval_policy=on-request",
                "-c",
                "sandbox_workspace_write.network_access=false",
            ],
            env={"PATH": "/bad/path"},
            cwd=str(self.root),
            stdin="brief",
        )

    def configure(self, rules):
        spec, overlay = codex_policy.configure_writer(self.spec, rules, self.root)
        if overlay:
            self.addCleanup(overlay.cleanup)
        return spec, overlay


    @real_proc("delegate: a worker, git or CLI process")
    def test_an_allowed_argv_runs_the_real_shim_without_a_prompt(self):
        spec, overlay = self.configure([["python", "-m", "unittest"]])
        assert overlay is not None
        command = [*overlay.prefix, "python", "-m", "unittest", "--help"]
        matching = [r for r in rules_at(overlay.root) if command[: len(r["pattern"])] == r["pattern"]]
        assert [r["decision"] for r in matching] == ["allow"]
        result = subprocess.run(command, env=os.environ | {"PATH": ""}, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        row = json.loads((self.root / "guard.jsonl").read_text().splitlines()[0])
        assert row["allowed"]
        assert row["resolved_argv"][0] == sys.executable
        assert "approval_policy=never" in spec.argv
