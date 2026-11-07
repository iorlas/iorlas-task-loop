"""`tl setup --plan` looks at a throwaway HOME and a repo and writes nothing."""
import argparse
import json
from pathlib import Path

from taskloop.app.doctor import setup
from taskloop.cli import setup as cli_setup
from taskloop.stores.delegate import real_route
from tlkernel.env import Env
from tlslots import profile_facts
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory


def tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


class SetupPlan(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.env = Env({"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")})
        self.plugin = self.home / "plugin"
        self.repo = self.home / "repo"
        self.repo.mkdir()

    def checks(self, plan):
        return {c.id: c for c in plan.checks}

    def test_a_bare_machine_is_planned_and_nothing_is_created(self):
        before = tree(self.home)
        plan = setup.plan(self.plugin, self.env, self.repo, profile_facts, real_route())
        assert tree(self.home) == before
        checks = self.checks(plan)
        assert not checks["config"].ok
        assert not checks["shim"].ok
        assert not checks["githooks"].ok
        assert {f.id for f in plan.fixes} == {"shim", "githooks"}  # no ~/.local here, so no PATH link to offer

    def test_a_local_folder_adds_the_path_link_fix_and_a_made_link_clears_it(self):
        (self.home / ".local").mkdir()
        assert "path-link" in {f.id for f in setup.plan(self.plugin, self.env, None, profile_facts, real_route()).fixes}
        (self.home / ".local" / "bin").mkdir()
        (self.home / ".local" / "bin" / "tl").symlink_to(self.home / ".config" / "task-loop" / "bin" / "tl")
        assert "path-link" not in {f.id for f in setup.plan(self.plugin, self.env, None, profile_facts, real_route()).fixes}

    def test_a_repo_without_a_profile_gets_the_questions_tailored_to_its_stack(self):
        (self.repo / "ProjectSettings").mkdir()
        (self.repo / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.0\n")
        (self.repo / "justfile").write_text("check:\n    true\n")
        plan = setup.plan(self.plugin, self.env, self.repo, profile_facts, real_route())
        assert [q.id for q in plan.questions] == ["unity-lease", "gate"]
        assert plan.questions[0].default == "yes"
        assert "unity" in self.checks(plan)["stack"].detail
        assert not self.checks(plan)["profile"].ok

    def test_a_unity_project_one_folder_down_is_found(self):
        (self.repo / "client" / "ProjectSettings").mkdir(parents=True)
        (self.repo / "client" / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.0\n")
        assert setup.stacks(self.repo) == {"unity": "client/ProjectSettings/ProjectVersion.txt"}

    def test_a_profile_that_loads_asks_nothing_and_a_stale_key_is_named(self):
        profile = self.repo / ".task-loop.json"
        profile.write_text(json.dumps({"slots": {"count": 2}}))
        plan = setup.repo_part(self.repo, profile_facts)
        assert plan.questions == []
        assert self.checks(plan)["profile"].ok
        profile.write_text(json.dumps({"slots": {"cuont": 2}}))
        stale = self.checks(setup.repo_part(self.repo, profile_facts))["profile"]
        assert not stale.ok
        assert "cuont" in stale.detail

    def test_slots_the_profile_counts_must_exist_on_disk(self):
        (self.repo / ".task-loop.json").write_text(json.dumps({"slots": {"count": 2}}))
        plan = setup.repo_part(self.repo, profile_facts)
        slots = self.checks(plan)["slots"]
        assert not slots.ok
        assert ".slots" in slots.detail
        assert [f.id for f in plan.fixes] == ["slots"]
        (self.repo / ".slots" / "s1").mkdir(parents=True)
        (self.repo / ".slots" / "s2").mkdir()
        done = setup.repo_part(self.repo, profile_facts)
        assert self.checks(done)["slots"].ok
        assert done.fixes == []

    def test_a_profile_with_no_slots_asks_nothing_about_them(self):
        (self.repo / ".task-loop.json").write_text(json.dumps({}))
        assert "slots" not in self.checks(setup.repo_part(self.repo, profile_facts))

    def test_the_command_prints_the_plan_as_json_or_text_and_exits_1_while_something_is_missing(self):
        shown = []
        args = argparse.Namespace(repo=str(self.repo), json=True, apply=False)
        assert cli_setup.cmd_setup(args, self.env, self.plugin, shown.append) == 1
        assert [c["id"] for c in json.loads(shown[0])["checks"]][:2] == ["config", "shim"]
        args.json = False
        cli_setup.cmd_setup(args, self.env, self.plugin, shown.append)
        assert shown[1].startswith("TODO config:")
