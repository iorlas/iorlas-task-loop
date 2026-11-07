"""`tl doctor`'s environment checks: bd as one healthy build, uv, Python, git identity, mise, TMPDIR and the config folder."""
import stat
from pathlib import Path

import pytest

from taskloop.app.doctor import env_checks as ec
from tlkernel.beadsport import BdError, BdFailure
from tlkernel.procport import Ran


class Runs:
    """A Runner that answers `<path> --version` from a table and records what it was asked."""

    def __init__(self, answers: dict[str, Ran]) -> None:
        self.answers, self.asked = answers, []

    def run(self, argv: list[str], *, cwd: str | None = None, timeout_s: float | None = None) -> Ran:
        self.asked.append(argv)
        if argv[0] not in self.answers:
            raise OSError("no such program")
        return self.answers[argv[0]]


def tool(folder: Path, name: str = "bd") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def opens() -> None:
    return None


def refuses() -> None:
    raise BdFailure(BdError(kind="other", text="table has unknown fields"))


def said(version: str) -> Ran:
    return Ran(exit=0, out=f"bd version {version} (abc123)\n")


def test_one_healthy_build_is_green(workdir):
    bd = tool(workdir / "a")
    assert ec.bd_findings(str(workdir / "a"), Runs({str(bd): said("1.3.1")}), opens, "/repo") == []


def test_no_bd_on_path_is_red_with_the_fix(workdir):
    got = ec.bd_findings(str(workdir / "empty"), Runs({}), opens, "/repo")
    assert [f.level for f in got] == ["FAIL"]
    assert "mise install" in got[0].fix


def test_two_builds_of_different_versions_are_red_and_the_fix_puts_the_newest_first(workdir):
    old, new = tool(workdir / "nix"), tool(workdir / "mise")
    path = f"{workdir / 'nix'}:{workdir / 'mise'}"
    got = ec.bd_findings(path, Runs({str(old): said("1.0.3"), str(new): said("1.3.1")}), opens, "/repo")
    assert [f.level for f in got] == ["FAIL"]
    assert "2 different bd builds" in got[0].text
    assert got[0].fix.endswith(f"export PATH={workdir / 'mise'}:$PATH")


def test_two_links_to_one_build_are_one_build(workdir):
    real = tool(workdir / "real")
    (workdir / "link").mkdir()
    (workdir / "link" / "bd").symlink_to(real)
    path = f"{workdir / 'link'}:{workdir / 'real'}"
    assert ec.bd_findings(path, Runs({str(workdir / "link" / "bd"): said("1.3.1")}), opens, "/repo") == []


def test_a_database_bd_cannot_open_is_red_and_says_the_build(workdir):
    old, new = tool(workdir / "nix"), tool(workdir / "mise")
    path = f"{workdir / 'nix'}:{workdir / 'mise'}"
    got = ec.bd_findings(path, Runs({str(old): said("1.0.3"), str(new): said("1.3.1")}), refuses, "/repo")
    assert [f.level for f in got] == ["FAIL", "FAIL"]
    assert "cannot open the database of /repo" in got[1].text and "table has unknown fields" in got[1].text
    assert "1.0.3" in got[1].text and str(new) in got[1].fix


def test_a_bd_that_does_not_run_is_red(workdir):
    bd = tool(workdir / "a")
    got = ec.bd_findings(str(workdir / "a"), Runs({str(bd): Ran(exit=2, err="boom")}), opens, "/repo")
    assert "does not run (exit 2): boom" in got[0].text


def test_a_mise_shim_under_an_untrusted_config_says_to_trust_it(workdir):
    bd = tool(workdir / "a")
    said = "mise ERROR Config files in /repo/mise.toml are not trusted.\nTrust them with `mise trust`."
    got = ec.bd_findings(str(workdir / "a"), Runs({str(bd): Ran(exit=1, err=said)}), opens, "/repo")
    assert "mise ERROR Config files in /repo/mise.toml are not trusted." in got[0].text
    assert "mise trust" in got[0].fix


@pytest.mark.parametrize(("text", "want"), [("bd version 1.3.1 (abc)", "1.3.1"), ("v2.0", "2.0"), ("no number", "")])
def test_the_version_is_the_first_dotted_number(text, want):
    assert ec.version_of(text) == want


class GitConfig:
    def __init__(self, **have: str) -> None:
        self.have = have

    def config_get(self, d: str, key: str) -> str:
        return self.have.get(key.replace(".", "_"), "")


def test_tools_are_green_when_all_resolve(workdir):
    path = str(workdir / "bin")
    tool(workdir / "bin", "uv")
    tool(workdir / "bin", "mise")
    runner = Runs({"mise": Ran(exit=0, out="")})
    assert ec.tool_findings(path, (3, 15, 0), runner, GitConfig(user_name="a", user_email="b"), "/repo") == []


def test_each_missing_tool_is_a_finding_with_its_fix(workdir):
    got = ec.tool_findings(str(workdir / "none"), (3, 12, 1), Runs({}), GitConfig(), "/repo")
    assert [(f.level, f.text.split()[0]) for f in got] == [("FAIL", "uv"), ("FAIL", "tl"), ("WARN", "git"), ("WARN", "mise")]
    assert "uv python install 3.15" in got[1].fix


def test_mise_tools_not_installed_are_a_warning(workdir):
    path = str(workdir / "bin")
    tool(workdir / "bin", "uv")
    tool(workdir / "bin", "mise")
    runner = Runs({"mise": Ran(exit=0, out="just  1.58.0  (missing)\n")})
    got = ec.tool_findings(path, (3, 15), runner, GitConfig(user_name="a", user_email="b"), "/repo")
    assert [(f.level, f.fix) for f in got] == [("WARN", "`mise install`")]


@pytest.mark.parametrize("tmp", ["", "/tmp", "/var/tmp/"])
def test_a_shared_or_unset_tmpdir_is_a_warning(tmp, workdir):
    got = ec.folder_findings(tmp, workdir)
    assert [f.level for f in got] == ["WARN"]
    assert "export TMPDIR=" in got[0].fix


def test_a_private_writable_tmpdir_and_config_are_green(workdir):
    (workdir / "tmp").mkdir()
    assert ec.folder_findings(str(workdir / "tmp"), workdir / "config") == []


def test_a_missing_tmpdir_is_red(workdir):
    got = ec.folder_findings(str(workdir / "gone"), workdir)
    assert [f.level for f in got] == ["FAIL"]
