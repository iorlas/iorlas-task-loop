"""`tl install REV --checkout PATH` through `main` (tl-8bh9.8.3 section 6.1): the progress lines as they come, the last
line, the refusal lines on stderr and the exit codes, over `cli_composition.install_ports` replaced by the fakes."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from install_doubles import CHECKOUT, FakeTools, TagRepo, install_ports, make_install

from taskloop import cli_composition
from taskloop.cli import main
from taskloop.cli_composition import UvTools
from taskloop.install_op import Ports, Ran
from taskloop.installs import LocalFiles, installs_root

FILES = {"pyproject.toml": ("100644", b"[project]\n")}


@pytest.fixture
def repo() -> TagRepo:
    found = TagRepo()
    commit = found.commit("main", FILES)
    found.named["refs/heads/main"] = commit
    found.named["refs/tags/light"] = commit
    found.annotate("factory-v0.2.0", commit)
    return found


def wire(monkeypatch: pytest.MonkeyPatch, home: Path, repo: TagRepo, tools: FakeTools) -> None:
    def ports(say: Callable[[str], None]) -> Ports:
        return replace(install_ports(home, repo, tools, []), say=say)

    monkeypatch.setattr(cli_composition, "install_ports", ports)


def install(rev: str) -> int:
    return main(["install", rev, "--checkout", str(CHECKOUT)])


def test_an_install_prints_its_progress_and_how_to_pin_it(tmp_path: Path, repo: TagRepo, monkeypatch: pytest.MonkeyPatch,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    wire(monkeypatch, tmp_path, repo, FakeTools())
    commit = repo.named["refs/heads/main"]
    folder = installs_root(tmp_path) / commit
    assert install("factory-v0.2.0") == 0
    out, err = capsys.readouterr()
    assert out.splitlines() == [
        f"Install: factory-v0.2.0 = {commit} (annotated tag) from {CHECKOUT}",
        f"Export: 1 files to {folder / 'source'}",
        f"Build: uv --project {commit}/source sync --frozen --no-editable --no-dev --reinstall-package iorlas-task-loop "
        f"(log {folder / 'install.log'})",
        "Resolved 12 packages", "Installed 12 packages",
        f"Verify: running from {folder / 'venv'}",
        f"Installed: {commit[:12]} (factory-v0.2.0); not pinned (tl pin factory-v0.2.0 runs it from the next start)",
    ] and err == ""


def test_a_commit_id_install_says_to_pin_the_commit(tmp_path: Path, repo: TagRepo, monkeypatch: pytest.MonkeyPatch,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    wire(monkeypatch, tmp_path, repo, FakeTools())
    commit = repo.named["refs/heads/main"]
    assert install(commit) == 0
    assert capsys.readouterr().out.splitlines()[-1] == (f"Installed: {commit[:12]}; not pinned (tl pin {commit} runs it from the "
                                                        "next start)")


def test_already_names_the_recorded_and_the_given_tag(tmp_path: Path, repo: TagRepo, monkeypatch: pytest.MonkeyPatch,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    commit = repo.named["refs/heads/main"]
    folder = make_install(tmp_path, commit, "factory-v0.1.0")
    wire(monkeypatch, tmp_path, repo, FakeTools())
    assert install("factory-v0.2.0") == 0
    assert capsys.readouterr().out.splitlines()[-1] == (f"Installed: already {commit[:12]} (factory-v0.1.0) (given as factory-v0.2.0) "
                                                        f"({folder})")
    assert install(commit) == 0
    assert capsys.readouterr().out.splitlines()[-1] == f"Installed: already {commit[:12]} (factory-v0.1.0) ({folder})"


@pytest.mark.parametrize(("rev", "tools", "code", "line"), [
    ("light", FakeTools(), 1, "tl install: refused not_annotated: tag light is a lightweight tag"),
    ("main", FakeTools(), 1, "tl install: refused revision: no tag main in the checkout"),
    ("factory-v0.2.0", FakeTools(uv=None), 3, "tl install: unavailable uv: uv is not on PATH"),
    ("factory-v0.2.0", FakeTools(raises=KeyboardInterrupt()), 130, "tl install: unavailable interrupted: "),
    ("factory-v0.2.0", FakeTools(ran=Ran(1, timed_out=False)), 1, "tl install: refused build: uv exited 1: Installed 12 packages"),
], ids=["not_annotated", "branch", "no_uv", "ctrl_c", "build"])
def test_refusals_go_to_stderr_with_their_exit_code(tmp_path: Path, repo: TagRepo, monkeypatch: pytest.MonkeyPatch,
                                                   capsys: pytest.CaptureFixture[str], rev: str, tools: FakeTools, code: int,
                                                   line: str) -> None:
    wire(monkeypatch, tmp_path, repo, tools)
    assert install(rev) == code
    err = capsys.readouterr().err
    assert err.startswith(line) and err.count("\n") == 1


def test_the_checkout_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["install", "factory-v0.2.0"])
    assert stopped.value.code == 2 and "--checkout" in capsys.readouterr().err


def test_the_real_ports_are_uv_on_path_the_local_files_and_this_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    said: list[str] = []
    ports = cli_composition.install_ports(said.append)
    assert isinstance(ports.tools, UvTools) and isinstance(ports.files, LocalFiles) and ports.home == tmp_path
    assert ports.now().tzinfo is not None
    ports.say("line")
    assert said == ["line"]
