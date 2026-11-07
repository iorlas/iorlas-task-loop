"""delegate-81g: `--engine-only RECIPE` is enforced by the harness of every lane that can write, or the lane is not routed a write step.
Claude: the PreToolUse hook. OpenCode: the bash deny rules of its permission config. Codex: no enforcement point, refused at route time."""

import copy
import json
import re
import subprocess
from pathlib import Path
from unittest import mock

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from test_review_order import CFG, T, lanes

from delegate.app import launch
from tltestkit.case import Case
from tltestkit.procsim import real_proc
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
DENIED_BY_OPENCODE = (
    "just slow",
    "just slow --verbose",
    "just -f x/justfile slow",
    "just --justfile x/justfile slow",
    "FOO=1 just slow",
    "cd client && just slow",
    'sh -c "just slow"',
    "bash -lc 'just slow'",
    "(just slow)",
    "make slow",
    "uv run slow",
    "pnpm slow",
    "ls && just slow | tee log",
)
PASSES = (
    "just test-fast",
    "just slower",
    "just fmt-check tests/slow.py",
    "python3 -m unittest discover -s tests",
    "git diff --stat",
    "ls slow",
)
TRAILS = ("", " *", '"*', "'*", ";*", "&*", "|*", ")*")


def hook_command(settings: dict) -> str:
    return settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def opencode_verdict(rules: dict[str, str], command: str) -> str:
    """OpenCode's wildcard match, restated here: `*` is any characters, the whole command must match, the last matching rule wins."""
    verdict = "ask"
    for pattern, action in rules.items():
        if re.fullmatch(".*".join(re.escape(x) for x in pattern.split("*")), command, re.S):
            verdict = action
    return verdict




class ClaudeHookTest:
    def hook(self, command: str, engine_only=("slow",), read_only=False):
        call = {"tool_name": "Bash", "tool_input": {"command": command}}
        with TemporaryDirectory() as tmp:
            Path(tmp, "host.json").write_text('{"binaries":{},"writer_exec_allow":[]}')
            with mock.patch("delegate.app.env.config_dir", return_value=Path(tmp)):
                argv = hook_command(launch.guard_settings(read_only, engine_only))
            r = subprocess.run(
                argv,
                shell=True,
                input=json.dumps(call),
                capture_output=True,
                text=True,
                check=False,
                env={"PATH": "/usr/bin:/bin", "DELEGATE_CONFIG_DIR": tmp, "HOME": tmp},
            )
        return r.returncode, r.stderr

    @real_proc("delegate: a worker, git or CLI process")
    def test_the_generated_hook_denies_the_recipe_with_the_rule(self):
        for c in ("just slow", "cd client && just slow", "FOO=1 just slow", "just -f x slow"):
            code, why = self.hook(c)
            assert code == 2, c
            assert "`just slow` is a check only the engine runs" in why
            assert "engine reruns the check" in why

    @real_proc("delegate: a worker, git or CLI process")
    def test_the_generated_hook_lets_other_commands_through_and_a_read_step_ignores_the_list(self):
        assert self.hook("just test-fast")[0] == 0
        assert self.hook("just slow", ())[0] == 0
        assert "slow" not in hook_command(launch.guard_settings(True, ("slow",)))


class RoutingTest(Case):
    def decide(self, *up, role="worker", **kw):
        return support.decide(role, copy.deepcopy(CFG), lanes(*up), {}, T, dict({"authored_by": None, "unattended": True}, **kw))

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_write_step_with_the_list_skips_codex_and_says_why(self):
        free = self.decide("openai", "xai", "claude")
        assert free["lane"] == "OPENAI_SUBSCRIPTION"
        d = self.decide("openai", "xai", "claude", engine_only=["slow"])
        assert (d["action"], d["lane"]) == ("run", "GROK_SUBSCRIPTION")
        assert "OPENAI_SUBSCRIPTION: rejected, its harness cannot deny the engine-only recipes slow to a write step" in d["trace"]




    @real_proc("delegate: a worker, git or CLI process")
    def test_advisory_runs_codex_with_or_without_a_family_pin(self):
        for pin in ([], ["openai"]):
            with self.subTest(pin=pin):
                d = self.decide("openai", "xai", "claude", only_family=pin, engine_only=["slow", "e2e"], engine_only_advisory=True)
                assert (d["action"], d["lane"], d["flag"]) == ("run", "OPENAI_SUBSCRIPTION", "engine_only_advisory")
                assert d["warning"] == "OPENAI_SUBSCRIPTION cannot deny --engine-only slow, e2e: advisory only, the brief must say so"
                assert not any("OPENAI_SUBSCRIPTION: rejected" in x for x in d["trace"])

    @real_proc("delegate: a worker, git or CLI process")
    def test_advisory_does_not_warn_when_enforcement_is_available_or_unneeded(self):
        for up, kw in (("claude", {"engine_only": ["slow"]}), ("openai", {}), ("openai", {"role": "reviewer", "engine_only": ["slow"]})):
            with self.subTest(up=up, kw=kw):
                d = self.decide(up, engine_only_advisory=True, **kw)
                assert d["action"] == "run"
                assert d["flag"] != "engine_only_advisory"
                assert "warning" not in d

    @real_proc("delegate: a worker, git or CLI process")
    def test_read_only_steps_ignore_the_list(self):
        assert self.decide("openai", role="reviewer", engine_only=["slow"])["lane"] == "OPENAI_SUBSCRIPTION"
