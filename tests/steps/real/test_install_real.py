"""Real layer, `tl install`'s Git side (tl-8bh9.8.3 sections 6.1 and 16): an annotated tag of a temporary repository is
resolved and exported through the real git_porcelain view `cli_composition.install_ports` opens (`Repo.tree`, `refs`,
`history`), bytes and modes compared; tree and blob ids, a lightweight tag and a tag's prefix are refused; the checkout's
refs, index and working tree are untouched. uv is the fake (`FakeTools`): the real build runs only in the live smoke. Set-up
runs through `git_porcelain.testing`'s runner under tmp_path."""

from dataclasses import replace
from pathlib import Path

import pytest
from git_porcelain.history import Identity
from git_porcelain.testing import apply_hermetic_env, git
from install_doubles import FakeTools

from taskloop import cli_composition
from taskloop.git_views import checkouts
from taskloop.install_op import Installed, Refused, install
from taskloop.installs import installs_root


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository with a plain and an executable file in a folder, tagged `factory-v1` (annotated), `factory-v1-rc`
    (annotated, on a later commit) and `light` (lightweight); a later uncommitted edit and a staged file."""
    home = tmp_path / "home"
    home.mkdir()
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={}, home=home)
    main = tmp_path.resolve() / "repo"
    (main / "bin").mkdir(parents=True)
    git(main, "init", "-q", "-b", "main")
    (main / "README").write_text("one\n")
    (main / "bin" / "run").write_bytes(b"#!/bin/sh\necho \xc3\xa9\n")
    (main / "bin" / "run").chmod(0o755)
    git(main, "add", "README", "bin/run")
    git(main, "commit", "-q", "-m", "base")
    git(main, "tag", "-a", "factory-v1", "-m", "factory v1")
    git(main, "tag", "light")
    (main / "README").write_text("two\n")
    git(main, "commit", "-q", "-am", "next")
    git(main, "tag", "-a", "factory-v1-rc", "-m", "rc")
    (main / "README").write_text("edited, not committed\n")
    (main / "staged").write_text("staged\n")
    git(main, "add", "staged")
    return main


def observed(main: Path) -> tuple[str, str, bytes]:
    return git(main, "for-each-ref"), git(main, "status", "--porcelain=v1"), (main / ".git" / "index").read_bytes()


def run(main: Path, rev: str, tools: FakeTools, said: list[str]) -> Installed | Refused:
    ports = replace(cli_composition.install_ports(said.append), tools=tools)
    found = install(rev, str(main), ports)
    assert isinstance(found, Installed | Refused), found
    return found


def test_an_annotated_tag_is_exported_from_git_objects_with_bytes_and_modes(checkout: Path) -> None:
    before = observed(checkout)
    commit = git(checkout, "rev-parse", "factory-v1^{commit}").strip()
    said: list[str] = []
    found = run(checkout, "factory-v1", FakeTools(), said)
    assert isinstance(found, Installed) and (found.manifest.commit, found.manifest.tag) == (commit, "factory-v1")
    source = installs_root(Path.home()) / commit / "source"
    assert (source / "README").read_text() == "one\n" and (source / "README").stat().st_mode & 0o777 == 0o644
    assert (source / "bin" / "run").read_bytes() == b"#!/bin/sh\necho \xc3\xa9\n"
    assert (source / "bin" / "run").stat().st_mode & 0o777 == 0o755
    assert sorted(path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file()) == ["README", "bin/run"]
    assert said[0] == f"Install: factory-v1 = {commit} (annotated tag) from {checkout}"
    assert observed(checkout) == before


def test_a_tree_id_has_no_history_and_tree_blob_and_lightweight_revisions_are_refused(checkout: Path) -> None:
    before = observed(checkout)
    tree = git(checkout, "rev-parse", "HEAD^{tree}").strip()
    blob = git(checkout, "rev-parse", "HEAD:README").strip()
    tag_object = git(checkout, "rev-parse", "factory-v1").strip()
    view = checkouts(checkout)
    assert view.tree(tree) is not None and view.history([tree], limit=1) == ()  # the plan's unverified premise (section 20)
    words = {rev: run(checkout, rev, FakeTools(), []) for rev in (tree, blob, tag_object, "light", "main", "factory")}
    assert {rev: found.word for rev, found in words.items() if isinstance(found, Refused)} == {
        tree: "revision", blob: "revision", tag_object: "revision", "light": "not_annotated", "main": "revision",
        "factory": "revision"}
    assert not installs_root(Path.home()).exists() and observed(checkout) == before


def test_a_tag_that_only_prefixes_another_is_not_taken(checkout: Path) -> None:
    rc = git(checkout, "rev-parse", "factory-v1-rc^{commit}").strip()
    found = run(checkout, "factory-v1-rc", FakeTools(), [])
    assert isinstance(found, Installed) and found.manifest.commit == rc
    git(checkout, "tag", "-d", "factory-v1")
    assert isinstance(found := run(checkout, "factory-v1", FakeTools(), []), Refused) and found.word == "revision"


def test_a_symlink_in_the_tree_is_refused_tree(checkout: Path) -> None:
    (checkout / "link").symlink_to("README")
    git(checkout, "add", "link")
    git(checkout, "commit", "-q", "-m", "link")
    head = git(checkout, "rev-parse", "HEAD").strip()
    tools = FakeTools()
    found = run(checkout, head, tools, [])
    assert isinstance(found, Refused) and found.word == "tree" and "link has mode 120000" in found.detail
    assert tools.runs == [] and not (installs_root(Path.home()) / head).exists()


def test_a_path_that_is_no_checkout_is_refused_checkout(tmp_path: Path, checkout: Path) -> None:
    del checkout
    elsewhere = tmp_path / "plain"
    elsewhere.mkdir()
    found = run(elsewhere, "factory-v1", FakeTools(), [])
    assert isinstance(found, Refused) and found.word == "checkout"
