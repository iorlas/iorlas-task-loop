"""`tl install REV --checkout PATH` (tl-8bh9.8.3 sections 6.1, 6.4, 11 and 16): REV checks over a repository's objects
(`TagRepo`), the install lock (the real lock library on tmp_path), the state under the lock, the native export, uv's
argv, working directory and environment (`FakeTools`), the verification and the manifest written last."""

import fcntl
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest
from git_porcelain import GitUnavailable, NotARepo
from install_doubles import (
    CHECKOUT,
    NOW,
    FakeTools,
    Files,
    Refusing,
    TagRepo,
    install_ports,
    make_install,
    make_pin,
    object_id,
)

from taskloop import start
from taskloop.install_op import Answer, Installed, Ran, Refused, Unavailable, install
from taskloop.installs import MANIFEST, LocalFiles, installs_root, state
from taskloop.repo import UnsupportedCheckout

FILES: Files = {"pyproject.toml": ("100644", b"[project]\nname = 'x'\n"), "tl.sh": ("100755", b"#!/bin/sh\n"),
                "src/taskloop/__init__.py": ("100644", b"")}
UV = ["--project", "{commit}/source", "sync", "--frozen", "--no-editable", "--no-dev", "--reinstall-package", "iorlas-task-loop"]


@pytest.fixture
def repo() -> TagRepo:
    """`main`'s commit tagged `factory-v0.2.0` (annotated), `light` (lightweight), `outer` (a tag of the annotated tag)."""
    found = TagRepo()
    commit = found.commit("main", FILES)
    found.named["refs/heads/main"] = commit
    found.named["refs/tags/light"] = commit
    tag = found.annotate("factory-v0.2.0", commit)
    found.annotate("outer", tag)
    return found


def main_commit(repo: TagRepo) -> str:
    return repo.named["refs/heads/main"]


def nothing_installed(home: Path, tools: FakeTools) -> bool:
    root = installs_root(home)
    return tools.runs == [] and tools.captures == [] and (not root.exists() or all(p.suffix == ".lock" for p in root.iterdir()))


def test_an_annotated_tag_is_exported_built_verified_and_its_manifest_written_last(tmp_path: Path, repo: TagRepo) -> None:
    tools, said = FakeTools(), []
    commit = main_commit(repo)
    found = install("factory-v0.2.0", str(CHECKOUT), install_ports(tmp_path, repo, tools, said))
    root = installs_root(tmp_path)
    folder = root / commit
    assert isinstance(found, Installed) and not found.already and found.install == folder
    assert said == [f"Install: factory-v0.2.0 = {commit} (annotated tag) from {CHECKOUT}",
                    f"Export: 3 files to {folder / 'source'}",
                    f"Build: uv {' '.join(UV).format(commit=commit)} (log {folder / 'install.log'})",
                    "Resolved 12 packages", "Installed 12 packages", f"Verify: running from {folder / 'venv'}"]
    assert {path: ((folder / "source" / path).read_bytes(), (folder / "source" / path).stat().st_mode & 0o777)
            for path in FILES} == {path: (data, 0o755 if mode == "100755" else 0o644) for path, (mode, data) in FILES.items()}
    assert tools.captures == [([str(folder / "venv" / "bin" / "python"), "-I", "-m", "taskloop", "version", "--json"], root)]
    complete = state(LocalFiles(), root, commit)
    assert complete.word == "complete" and complete.manifest == found.manifest
    assert (found.manifest.tag, found.manifest.installed_at, found.manifest.checkout) == ("factory-v0.2.0", "2026-11-20T10:05:00Z",
                                                                                          str(CHECKOUT))
    assert (folder / "install.log").read_text().splitlines()[:3] == [said[2], "Resolved 12 packages", "Installed 12 packages"]


def test_uv_runs_from_the_installs_root_with_the_exact_argv_and_no_uv_or_virtualenv_variable(tmp_path: Path, repo: TagRepo) -> None:
    tools = FakeTools()
    commit = main_commit(repo)
    install(commit, str(CHECKOUT), install_ports(tmp_path, repo, tools, []))
    [(argv, cwd, env)] = tools.runs
    assert argv == ["/opt/uv/bin/uv", *(part.format(commit=commit) for part in UV)]
    assert cwd == installs_root(tmp_path)
    assert env == {"PATH": "/usr/bin", "HOME": "/home/u", "UV_PROJECT_ENVIRONMENT": str(installs_root(tmp_path) / commit / "venv"),
                   "UV_NO_CONFIG": "1"}


def test_a_full_commit_id_installs_without_a_tag(tmp_path: Path, repo: TagRepo) -> None:
    said: list[str] = []
    commit = main_commit(repo)
    found = install(commit, str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(), said))
    assert isinstance(found, Installed) and found.manifest.tag is None and found.asked is None
    assert said[0] == f"Install: {commit} (commit) from {CHECKOUT}"


def test_a_tag_of_a_tag_peels_to_its_commit(tmp_path: Path, repo: TagRepo) -> None:
    found = install("outer", str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(), []))
    assert isinstance(found, Installed) and (found.manifest.commit, found.manifest.tag) == (main_commit(repo), "outer")


@pytest.mark.parametrize("rev", ["main", "tree", "blob", "tag_object", "short", "missing_commit", "missing_tag", "tag_of_tree",
                                 "bad_name", "option"])
def test_anything_but_an_annotated_tag_or_a_commit_id_is_refused_revision(tmp_path: Path, repo: TagRepo, rev: str) -> None:
    """A branch, a tree or blob id (`Repo.tree` accepts a tree id: its history is empty), a tag object's own id, a short id,
    an unknown commit or tag, a tag of a tree, a name that is no tag name."""
    commit = main_commit(repo)
    repo.named["refs/tags/treetag"] = repo.tree_of(commit)
    given = {"main": "main", "tree": repo.tree_of(commit), "blob": object_id("blob tl.sh"),
             "tag_object": repo.named["refs/tags/factory-v0.2.0"], "short": commit[:12], "missing_commit": "0" * 40,
             "missing_tag": "factory-v9", "tag_of_tree": "treetag", "bad_name": "a..b", "option": "--all"}[rev]
    tools = FakeTools()
    found = install(given, str(CHECKOUT), install_ports(tmp_path, repo, tools, []))
    assert isinstance(found, Refused) and found.word == "revision"
    assert nothing_installed(tmp_path, tools) and not installs_root(tmp_path).exists()


def test_a_lightweight_ref_to_an_annotated_tag_object_is_accepted_by_rule(tmp_path: Path, repo: TagRepo) -> None:
    """The rule is "the ref names another object than its commit": a lightweight `alias` of `factory-v0.2.0`'s tag object
    passes it (plan section 6.1)."""
    repo.named["refs/tags/alias"] = repo.named["refs/tags/factory-v0.2.0"]
    found = install("alias", str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(), []))
    assert isinstance(found, Installed) and (found.manifest.commit, found.manifest.tag) == (main_commit(repo), "alias")


def test_a_lightweight_tag_is_not_annotated(tmp_path: Path, repo: TagRepo) -> None:
    tools = FakeTools()
    found = install("light", str(CHECKOUT), install_ports(tmp_path, repo, tools, []))
    assert isinstance(found, Refused) and found.word == "not_annotated"
    assert not installs_root(tmp_path).exists()


def test_only_the_exactly_named_tag_counts_never_one_it_prefixes(tmp_path: Path, repo: TagRepo) -> None:
    """`refs/tags/v1` as a listing prefix also lists `refs/tags/v1-rc`: only the exact name is taken."""
    other = repo.commit("rc", {"rc.txt": ("100644", b"rc\n")})
    repo.annotate("v1-rc", other)
    assert isinstance(found := install("v1", str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(), [])), Refused)
    assert found.word == "revision"
    repo.annotate("v1", main_commit(repo))
    found = install("v1", str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(), []))
    assert isinstance(found, Installed) and found.manifest.commit == main_commit(repo)


@pytest.mark.parametrize(("path", "mode"), [("link", "120000"), ("vendor/lib", "160000"), ("a//b", "100644"), ("./x", "100644"),
                                            ("../escape", "100644"), (".git/config", "100644"),
                                            ("src/.GIT/hooks", "100644"), ("PyProject.toml", "100644"), ("TL.sh/x", "100644")])
def test_a_symlink_gitlink_or_unsafe_path_is_refused_tree_before_anything_is_written(tmp_path: Path, path: str, mode: str) -> None:
    repo = TagRepo()
    commit = repo.commit("main", {**FILES, path: (mode, b"x")})
    tools = FakeTools()
    found = install(commit, str(CHECKOUT), install_ports(tmp_path, repo, tools, []))
    assert isinstance(found, Refused) and found.word == "tree" and path.split("/", 1)[0] in found.detail
    assert nothing_installed(tmp_path, tools) and repo.reads == []


def test_folders_that_differ_only_in_case_merge_harmlessly_and_are_installed(tmp_path: Path) -> None:
    repo = TagRepo()
    commit = repo.commit("main", {**FILES, "Src/other.py": ("100644", b"")})
    assert isinstance(install(commit, str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(), [])), Installed)


def test_without_uv_on_path_nothing_is_exported(tmp_path: Path, repo: TagRepo) -> None:
    tools = FakeTools(uv=None)
    found = install(main_commit(repo), str(CHECKOUT), install_ports(tmp_path, repo, tools, []))
    assert found == Unavailable("uv", "uv is not on PATH") and nothing_installed(tmp_path, tools)


@pytest.mark.parametrize(("error", "word"), [(UnsupportedCheckout("a subdirectory"), "checkout"), (NotARepo("not a repo"), "checkout"),
                                             (FileNotFoundError(2, "gone"), "checkout"), (GitUnavailable("git broke"), "git")])
def test_a_checkout_that_cannot_be_read(tmp_path: Path, error: Exception, word: str) -> None:
    tools = FakeTools()
    found = install("factory-v0.2.0", str(CHECKOUT), install_ports(tmp_path, error, tools, []))
    assert isinstance(found, Refused if word == "checkout" else Unavailable) and found.word == word
    assert nothing_installed(tmp_path, tools)


def test_a_listed_blob_that_cannot_be_read_is_git_unavailable_and_left_incomplete(tmp_path: Path, repo: TagRepo) -> None:
    repo.unreadable.add("tl.sh")
    tools = FakeTools()
    commit = main_commit(repo)
    found = install(commit, str(CHECKOUT), install_ports(tmp_path, repo, tools, []))
    assert isinstance(found, Unavailable) and found.word == "git" and tools.runs == []
    assert "tl.sh" in found.detail and "left without a manifest" in found.detail
    repo.unreadable.clear()
    assert_left_incomplete(tmp_path, repo, commit)


def test_an_installs_folder_that_cannot_be_made_is_write_unavailable(tmp_path: Path, repo: TagRepo) -> None:
    (tmp_path / ".local").write_text("a file where a folder belongs\n")
    found = install(main_commit(repo), str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(), []))
    assert isinstance(found, Unavailable) and found.word == "write"


def files_under(root: Path) -> list[Path]:
    """Everything under the installs root but the lock files (made by the lock, never removed)."""
    return sorted(path.relative_to(root) for path in root.rglob("*") if path.suffix != ".lock")


def assert_left_incomplete(home: Path, repo: TagRepo, commit: str) -> None:
    """The directory stays without a manifest, and the next install refuses `incomplete` naming it, removing nothing."""
    root = installs_root(home)
    assert state(LocalFiles(), root, commit).word == "incomplete"
    before = files_under(root)
    tools = FakeTools()
    again = install(commit, str(CHECKOUT), install_ports(home, repo, tools, []))
    assert isinstance(again, Refused) and again.word == "incomplete" and str(root / commit) in again.detail
    assert f"grep {commit[:12]}" in again.detail and "remove the directory" in again.detail
    assert "an earlier install did not finish" in again.detail
    assert tools.runs == [] and files_under(root) == before


@pytest.mark.parametrize(("ran", "ended"), [(Ran(2, timed_out=False), "uv exited 2"), (Ran(None, timed_out=True), "uv timed out"),
                                            (Ran(None, timed_out=False, signal=9), "uv ended by signal 9"),
                                            (Ran(None, timed_out=True, survivors=(41, 42)), "uv timed out after 900 s; its process "
                                             "tree may still be writing (pids 41 42)")])
def test_a_failed_build_names_its_last_line_and_log_and_writes_no_manifest(tmp_path: Path, repo: TagRepo, ran: Ran, ended: str) -> None:
    tools = FakeTools(ran=ran, lines=("Resolved 12 packages", "error: lock file is stale", "   "))
    commit = main_commit(repo)
    found = install(commit, str(CHECKOUT), install_ports(tmp_path, repo, tools, []))
    log = installs_root(tmp_path) / commit / "install.log"
    assert isinstance(found, Refused) and found.word == "build"
    assert found.detail.startswith(f"{ended}") and "error: lock file is stale" in found.detail and f"(log {log})" in found.detail
    assert tools.captures == [] and "left without a manifest" in found.detail and "interrupted" not in found.detail
    assert_left_incomplete(tmp_path, repo, commit)


def test_ctrl_c_during_the_build_is_interrupted_and_leaves_the_directory_incomplete(tmp_path: Path, repo: TagRepo) -> None:
    commit = main_commit(repo)
    found = install(commit, str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(raises=KeyboardInterrupt()), []))
    assert isinstance(found, Unavailable) and found.word == "interrupted" and str(installs_root(tmp_path) / commit) in found.detail
    assert_left_incomplete(tmp_path, repo, commit)  # the lock was released: `incomplete`, not `busy`


class Killed(BaseException):
    """The operation ends without unwinding into it, as a `kill -9` or a hang-up ends `tl install` while uv may run on."""


def test_an_orphaned_build_leaves_the_next_install_refused_incomplete(tmp_path: Path, repo: TagRepo) -> None:
    commit = main_commit(repo)
    with pytest.raises(Killed):
        install(commit, str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(raises=Killed()), []))
    assert (installs_root(tmp_path) / commit / "source" / "tl.sh").exists()
    assert_left_incomplete(tmp_path, repo, commit)


def bad_prefix(tmp_path: Path) -> Answer:
    return Answer(0, '{"running": {"prefix": "' + str(tmp_path / "runner" / ".venv") + '"}}', timed_out=False)


@pytest.mark.parametrize("answer", ["not_json", "no_prefix", "other_prefix", "timeout", "exit"])
def test_a_verification_that_fails_writes_no_manifest(tmp_path: Path, repo: TagRepo, answer: str) -> None:
    given = {"not_json": Answer(0, "Running: unmanaged", timed_out=False), "no_prefix": Answer(0, '{"running": null}', timed_out=False),
             "other_prefix": bad_prefix(tmp_path), "timeout": Answer(124, "", timed_out=True),
             "exit": Answer(1, "Traceback", timed_out=False)}[answer]
    commit = main_commit(repo)
    found = install(commit, str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(answer=given), []))
    assert isinstance(found, Refused) and found.word == "verify"
    assert_left_incomplete(tmp_path, repo, commit)


def snapshot(root: Path) -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in root.rglob("*")}


def test_a_complete_install_is_already_and_nothing_is_written(tmp_path: Path, repo: TagRepo) -> None:
    commit = main_commit(repo)
    folder = make_install(tmp_path, commit, "factory-v0.1.0")
    before = snapshot(folder)
    tools, said = FakeTools(), []
    found = install("factory-v0.2.0", str(CHECKOUT), install_ports(tmp_path, repo, tools, said))
    assert isinstance(found, Installed) and found.already and found.install == folder
    assert (found.manifest.tag, found.asked) == ("factory-v0.1.0", "factory-v0.2.0")  # a moved tag: the same install
    assert tools.runs == [] and repo.reads == [] and snapshot(folder) == before and len(said) == 1


def test_a_broken_manifest_is_refused_broken_as_installs_state_says(tmp_path: Path, repo: TagRepo) -> None:
    commit = main_commit(repo)
    folder = make_install(tmp_path, commit, manifest="format = 2\n")
    assert state(LocalFiles(), installs_root(tmp_path), commit).word == "broken"
    tools = FakeTools()
    found = install(commit, str(CHECKOUT), install_ports(tmp_path, repo, tools, []))
    assert isinstance(found, Refused) and found.word == "broken" and str(folder) in found.detail and "format is 2" in found.detail
    assert tools.runs == [] and (folder / MANIFEST).read_text() == "format = 2\n"


def test_an_existing_directory_without_a_manifest_is_refused_incomplete_and_kept(tmp_path: Path, repo: TagRepo) -> None:
    commit = main_commit(repo)
    (installs_root(tmp_path) / commit / "venv").mkdir(parents=True)
    assert_left_incomplete(tmp_path, repo, commit)


@contextmanager
def another_install(lock: Path) -> Generator[None]:
    """Another `tl install` of the same commit holding its lock: its own open file description with the `flock`."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def test_while_another_install_holds_the_lock_readers_see_incomplete_and_install_is_busy(tmp_path: Path, repo: TagRepo) -> None:
    """The manifest-vs-lock race: a build in progress (its directory, no manifest) under the lock; the resolver and every
    other reader take no lock and see `incomplete`, a second install refuses `busy` and writes nothing."""
    commit = main_commit(repo)
    root = installs_root(tmp_path)
    (root / commit / "source").mkdir(parents=True)
    make_pin(tmp_path, commit, "factory-v0.2.0")
    with another_install(root / f"{commit}.lock"):
        assert state(LocalFiles(), root, commit).word == "incomplete"
        resolved = start.resolve(["step", "list"], tmp_path, "/usr/bin/python3", LocalFiles())
        assert isinstance(resolved, start.PinRefused) and resolved.word == "pin:incomplete"
        tools = FakeTools()
        found = install(commit, str(CHECKOUT), install_ports(tmp_path, repo, tools, []))
        assert isinstance(found, Refused) and found.word == "busy" and tools.runs == []
        assert sorted(path.name for path in (root / commit).iterdir()) == ["source"]


class Pausing(LocalFiles):
    """The local files, observing the install's state between the manifest's temporary write and its rename."""

    def __init__(self, root: Path, commit: str) -> None:
        self.root, self.commit, self.seen = root, commit, []

    def replace(self, source: Path, target: Path) -> None:
        self.seen.append(state(LocalFiles(), self.root, self.commit).word)
        super().replace(source, target)
        self.seen.append(state(LocalFiles(), self.root, self.commit).word)


def test_a_reader_during_the_manifest_write_sees_no_manifest_or_the_whole_one(tmp_path: Path, repo: TagRepo) -> None:
    commit = main_commit(repo)
    files = Pausing(installs_root(tmp_path), commit)
    found = install(commit, str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(), [], files))
    assert isinstance(found, Installed) and files.seen == ["incomplete", "complete"]
    assert [path.name for path in (installs_root(tmp_path) / commit).iterdir() if path.name.endswith(".tmp")] == []


def test_the_manifest_records_the_clock_in_utc(tmp_path: Path, repo: TagRepo) -> None:
    found = install(main_commit(repo), str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(), []))
    assert isinstance(found, Installed) and found.manifest.installed_at == NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_ctrl_c_partway_through_the_export_is_interrupted(tmp_path: Path, repo: TagRepo) -> None:
    def stop(count: int) -> None:
        if count == 2:
            raise KeyboardInterrupt

    repo.on_read = stop
    commit = main_commit(repo)
    tools = FakeTools()
    found = install(commit, str(CHECKOUT), install_ports(tmp_path, repo, tools, []))
    assert isinstance(found, Unavailable) and found.word == "interrupted" and "left without a manifest" in found.detail
    assert tools.runs == []
    repo.on_read = None
    assert_left_incomplete(tmp_path, repo, commit)


def test_a_folder_that_cannot_be_written_during_the_export_is_write_unavailable(tmp_path: Path, repo: TagRepo) -> None:
    commit = main_commit(repo)
    source = installs_root(tmp_path) / commit / "source"

    def seal(count: int) -> None:
        if count == 2:
            source.chmod(0o500)

    repo.on_read = seal
    try:
        found = install(commit, str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(), []))
        assert isinstance(found, Unavailable) and found.word == "write" and "left without a manifest" in found.detail
        repo.on_read = None
        assert_left_incomplete(tmp_path, repo, commit)
    finally:
        source.chmod(0o700)


def test_no_space_for_the_manifest_is_write_unavailable_and_left_incomplete(tmp_path: Path, repo: TagRepo) -> None:
    commit = main_commit(repo)
    found = install(commit, str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(), [], Refusing(failing="write")))
    assert isinstance(found, Unavailable) and found.word == "write" and "No space left" in found.detail
    assert "left without a manifest" in found.detail
    assert_left_incomplete(tmp_path, repo, commit)


def test_a_log_that_cannot_be_written_is_reported_not_truncated(tmp_path: Path, repo: TagRepo) -> None:
    def replace_log(install_folder: Path) -> None:
        (install_folder / "install.log").unlink()
        (install_folder / "install.log").mkdir()

    commit = main_commit(repo)
    found = install(commit, str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(before=replace_log), []))
    assert isinstance(found, Unavailable) and found.word == "write" and "install.log" in found.detail
    assert state(LocalFiles(), installs_root(tmp_path), commit).word == "incomplete"


def test_a_closed_terminal_never_stops_the_install_or_its_log(tmp_path: Path, repo: TagRepo) -> None:
    def closed(_text: str) -> None:
        raise BrokenPipeError(32, "Broken pipe")

    commit = main_commit(repo)
    found = install(commit, str(CHECKOUT), install_ports(tmp_path, repo, FakeTools(), [], say=closed))
    assert isinstance(found, Installed)
    assert "Installed 12 packages" in (installs_root(tmp_path) / commit / "install.log").read_text()
