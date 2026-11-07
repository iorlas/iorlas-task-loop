"""One repo's bad .task-loop.json is a RED row for that repo (file and key named); doctor and the other repos go on."""
import contextlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401
from support import homes
from support.checked import run_checked
from support.repos import write_repos
from support.spawn import port_git
from support.who import who

from taskloop.app.doctor import profiles
from taskloop.app.launch import dash_ports
from taskloop.app.launch import loop_start as wstart
from taskloop.app.wire import brief, doctor
from tlkernel.env import snapshot
from tlkernel.paths import ConfigDir
from tlkernel.rowstores import ReposStore

ROOT = Path(__file__).resolve().parents[3]
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class BadProfile(Case):
    def setup_method(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        patch = mock.patch.dict(os.environ, dict(GIT_ENV, XDG_CONFIG_HOME=str(root / "cfg"), CLAUDE_CONFIG_DIR=str(root / "claude")))
        patch.start()
        self.addCleanup(patch.stop)
        self.good, self.bad = root / "good", root / "bad"
        for repo, profile in ((self.good, {"slots": {"count": 0}}), (self.bad, {"engine": {"checks": [{"id": "t", "cmd": "just test"}]}})):
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=os.environ)
            (repo / ".task-loop.json").write_text(json.dumps(profile))
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=os.environ)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x"], check=True, env=os.environ)
        cfg = root / "cfg" / "task-loop"
        cfg.mkdir(parents=True)
        write_repos(cfg / "repos.json", self.good, self.bad)

    def doctor(self, repo: Path, plugin_root: Path = ROOT) -> tuple[int, str]:
        out = io.StringIO()
        old = os.getcwd()
        os.chdir(repo)
        try:
            with contextlib.redirect_stdout(out):
                rc = doctor.run(plugin_root, snapshot(), port_git(), who())
        finally:
            os.chdir(old)
        return rc, out.getvalue()

    def test_the_row_names_the_file_and_the_key(self) -> None:
        row = profiles.red_row(port_git(),self.bad)
        assert row.startswith("RED "), row
        assert str(self.bad / ".task-loop.json") in row
        assert "checks" in row
        assert profiles.red_row(port_git(),self.good) == ""

    def test_doctor_in_the_good_repo_succeeds_and_shows_the_bad_repos_row(self) -> None:
        rc, text = self.doctor(self.good)
        assert rc == 0, text
        assert f"RED {self.bad}" in text
        assert "Traceback" not in text

    def test_doctor_fails_with_a_FAIL_line_when_the_plugin_has_no_ownership_section(self) -> None:
        bare = self.good.parent / "plugin"
        bare.mkdir()
        (bare / "AGENTS.md").write_text("# no section\n")
        rc, text = self.doctor(self.good, bare)
        assert rc == 1
        assert re.search(r"(?m)^FAIL .*Ownership", text)

    def test_doctor_in_the_bad_repo_is_a_row_and_exit_1_not_a_traceback(self) -> None:
        rc, text = self.doctor(self.bad)
        assert rc == 1
        assert sum(1 for ln in text.splitlines() if ln.startswith("RED ")) == 1

    def test_walking_the_registered_repos_skips_the_one_asked_from(self) -> None:
        rows = profiles.red_rows(port_git(),profiles.registered(ReposStore(homes.cfg())), but=str(self.good))
        assert len(rows) == 1
        assert profiles.red_rows(port_git(),[str(self.bad)], but=str(self.bad)) == []


STALE: dict[str, object] = {"engine": {"checks": [{"id": "t", "cmd": "just test"}]}}  # a string check: bad
GOOD: dict[str, object] = {"engine": {"checks": [{"id": "t", "argv": ["just", "test"]}]}}


class SourceIsTheBaseCommit(Case):
    """The loop reads the profile off the base commit; doctor must read the same one, not a stale checkout."""

    def setup_method(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ, GIT_ENV)
        patch.start()
        self.addCleanup(patch.stop)
        self.repo = Path(tmp.name).resolve() / "r"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True, env=os.environ)

    def commit(self, profile: dict[str, object], base: bool) -> None:
        (self.repo / ".task-loop.json").write_text(json.dumps(profile))
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True, env=os.environ)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "x"], check=True, env=os.environ)
        if base:
            subprocess.run(["git", "-C", str(self.repo), "update-ref", "refs/remotes/origin/main", "HEAD"], check=True, env=os.environ)

    def sha7(self) -> str:
        done = run_checked(["git", "-C", str(self.repo), "rev-parse", "--short=7", "origin/main"], None, env=os.environ, text=True)
        return done.stdout.strip()

    def test_a_stale_working_tree_under_a_good_base_commit_is_no_red_row(self) -> None:
        self.commit(GOOD, base=True)
        (self.repo / ".task-loop.json").write_text(json.dumps(STALE))
        assert profiles.red_row(port_git(),self.repo) == ""
        says: list[str] = []
        assert not profiles.report(port_git(),str(self.repo), ReposStore(ConfigDir(self.repo / "none")), says.append)
        assert says == [f"profile: {self.repo} read from base {self.sha7()}"]

    def test_a_bad_base_commit_is_a_row_naming_the_source(self) -> None:
        self.commit(STALE, base=True)
        (self.repo / ".task-loop.json").write_text(json.dumps(GOOD))
        row = profiles.red_row(port_git(),self.repo)
        assert row.startswith("RED "), row
        assert f"(base {self.sha7()})" in row

    def test_no_base_commit_falls_back_to_the_working_tree(self) -> None:
        self.commit(GOOD, base=False)
        assert profiles.red_row(port_git(),self.repo) == ""
        (self.repo / ".task-loop.json").write_text(json.dumps(STALE))
        assert "(working tree)" in profiles.red_row(port_git(),self.repo)


class OtherViews(BadProfile):
    """`tl status` and the dashboard's ports show the bad repo as a red row; the good repo's own view works."""

    def test_status_in_the_good_repo_shows_the_bad_repos_red_row(self) -> None:
        with mock.patch.object(brief.wslots, "slot_beads", return_value=[]):
            text = brief.status_text(str(self.good), ROOT, 0.0, False, snapshot(), who(), port_git())
            data = json.loads(brief.status_text(str(self.good), ROOT, 0.0, True, snapshot(), who(), port_git()))
        assert f"RED {self.bad}" in text
        assert str(self.bad / ".task-loop.json") in text
        assert [r.split(":")[0] for r in data["red"]] == [f"RED {self.bad}"]
        assert "Traceback" not in text

    def test_the_dash_ports_name_the_bad_repo_only(self) -> None:
        ports = dash_ports.ports(snapshot())
        assert ports.profile_error(str(self.good)) == ""
        assert str(self.bad / ".task-loop.json") in ports.profile_error(str(self.bad))

    def test_cutover_over_a_bad_repo_is_not_a_traceback(self) -> None:
        assert wstart.live_work(port_git(), who()) == []
