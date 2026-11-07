"""`tl setup --apply`: the machine fixes in a throwaway HOME and the profile as a PR, over a recording runner."""
import argparse
import base64
import json
from pathlib import Path

from taskloop.app.doctor import setup, setup_apply
from taskloop.app.slots import config as slots_config
from taskloop.app.slots import profile_facts
from taskloop.cli import setup as cli_setup
from tlkernel.env import Env
from tlkernel.procport import Ran
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]


class Recorder:
    """Answers the `gh` calls the way gh does: the base branch name, a sha, then whatever the step prints."""

    def __init__(self, fail_on: str = ""):
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def run(self, argv: list[str], *, cwd: str | None = None) -> Ran:
        self.calls.append(argv)
        failed = self.fail_on != "" and any(self.fail_on in a for a in argv)
        out = {"repo": "main", "api": "abc123"}.get(argv[1], "https://example.test/pr/1")
        return Ran(exit=1 if failed else 0, out=out, err="refused" if failed else "")

    def committed(self) -> dict[str, object]:
        put = next(c for c in self.calls if "PUT" in c)
        return json.loads(base64.b64decode(next(a for a in put if a.startswith("content=")).removeprefix("content=")))


class SetupApply(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.env = Env({"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")})
        (self.home / "cache").mkdir()
        self.plugin = self.home / "cache" / "0.9.9"  # an install by its version number, as the plugin cache has it: the shim resolves
        self.plugin.symlink_to(ROOT)
        self.repo = self.home / "repo"
        self.repo.mkdir()
        (self.repo / "justfile").write_text("check:\n    true\n")

    def test_the_machine_fixes_are_made_and_a_second_run_has_nothing_left(self):
        code, lines = setup_apply.apply(self.plugin, self.env, None, {}, Recorder(), profile_facts)
        assert code == 0
        assert {"shim", "githooks"} <= {line.removeprefix("fixed ") for line in lines}
        machine = setup.machine(self.plugin, self.env).checks
        assert all(c.ok for c in machine if c.id not in ("path-link", "accounts"))  # accounts: this machine's logins
        assert setup_apply.apply(self.plugin, self.env, None, {}, Recorder(), profile_facts)[1] == ["machine: nothing to fix"]

    def test_the_answers_make_a_profile_the_loader_accepts(self):
        for answers in ({"gate": "no"}, {"unity-lease": "yes", "gate": "yes"}, {"gate": "yes"}):
            with self.subTest(answers=answers):
                slots_config.load_profile(setup_apply.profile_of(answers))

    def test_a_profile_goes_in_as_a_pr_over_gh_alone(self):
        sh = Recorder()
        code, lines = setup_apply.apply(self.plugin, self.env, self.repo, {"gate": "yes"}, sh, profile_facts)
        assert code == 0
        assert lines[-1] == "profile: PR https://example.test/pr/1"
        assert sh.committed() == {"engine": {"checks": [{"id": "gate", "argv": ["just", "check"]}]}}
        assert {c[0] for c in sh.calls} == {"gh"}
        assert [c[1] for c in sh.calls] == ["repo", "api", "api", "api", "pr"]
        assert "--base" in sh.calls[-1]
        assert sh.calls[-1][sh.calls[-1].index("--base") + 1] == "main"

    def test_the_unity_lease_answer_writes_host_json_once_and_keeps_a_persons_file(self):
        (self.repo / "ProjectSettings").mkdir()
        (self.repo / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.0\n")
        answers = {"unity-lease": "yes", "gate": "yes"}
        setup_apply.apply(self.plugin, self.env, self.repo, answers, Recorder(), profile_facts)
        host = self.home / ".config" / "task-loop" / "host.json"
        assert json.loads(host.read_text())["resources"] == ["unity"]
        host.write_text(json.dumps({"resources": []}))
        _, lines = setup_apply.apply(self.plugin, self.env, self.repo, answers, Recorder(), profile_facts)
        assert json.loads(host.read_text())["resources"] == []
        assert not any("host.json" in line for line in lines)

    def test_a_missing_answer_opens_nothing_and_a_failed_step_is_named(self):
        sh = Recorder()
        code, lines = setup_apply.apply(self.plugin, self.env, self.repo, {}, sh, profile_facts)
        assert code == 1
        assert "no answer for gate" in lines[-1]
        assert sh.calls == []
        code, lines = setup_apply.apply(self.plugin, self.env, self.repo, {"gate": "no"}, Recorder(fail_on="PUT"), profile_facts)
        assert code == 1
        assert "gh api contents failed: refused" in lines[-1]

    def test_the_command_reads_answers_from_a_file_and_yes_takes_the_defaults(self):
        shown: list[str] = []
        path = self.home / "answers.json"
        path.write_text(json.dumps({"gate": "no"}))
        args = argparse.Namespace(repo=str(self.repo), apply=True, json=False, answers=str(path), yes=False)
        assert cli_setup.cmd_setup(args, self.env, self.plugin, shown.append, Recorder()) == 0
        sh = Recorder()
        args = argparse.Namespace(repo=str(self.repo), apply=True, json=False, answers=None, yes=True)
        assert cli_setup.cmd_setup(args, self.env, self.plugin, shown.append, sh) == 0
        assert sh.committed() == {"engine": {"checks": [{"id": "gate", "argv": ["just", "check"]}]}}
