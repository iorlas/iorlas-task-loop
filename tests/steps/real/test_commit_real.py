"""Real layer, one wiring test of the step commit on the real Git adapter (git_porcelain's own contract suite covers
`stage`, `record`, `dirty` and `history`): through `composition.checkouts` and `RealSlotFiles` no repository hook runs,
the commit carries the trailer and the slot ends clean; a symlinked listed path is refused before anything is staged.
The slot pointer is judged with Git's own resolution: a pointer that names the right Git directory only lexically (a
symlink inside the slot redirects it to the person's `.git` or to a fake Git directory whose filter would run) is
`redirected` before any Git call, while `git worktree add --relative-paths` is accepted. A crash leftover is adopted
through real `history` by its trailer. Set-up runs through `git_porcelain.testing`'s runner under tmp_path."""

from dataclasses import replace
from pathlib import Path

import pytest
from git_porcelain import GitUnavailable
from git_porcelain.history import Identity
from git_porcelain.testing import apply_hermetic_env, git

from taskloop.attempt_types import Admission, AnswerState, AttemptKey, ChainLink, FileRef, Rejected, Unsettled
from taskloop.composition import RealSlotFiles, checkouts
from taskloop.factory_commit import Committed, clean_at, settle
from taskloop.repo import RepoId
from taskloop.slot_state import pointer
from taskloop.steps import IMPLEMENT
from taskloop.task import TaskReference, TaskScope
from taskloop.verdict import judge

P = "docs/design/tl-1/plan.md"
HOOKS = ("pre-commit", "commit-msg", "prepare-commit-msg", "post-commit", "post-index-change", "reference-transaction")
ANSWER = AnswerState("valid", "planned", "commit", (P,), "Plan tl-1")


def quiet() -> Unsettled | None:
    """The worker is gone and the attempt holds its reservation (these tests run no agent)."""
    return None


def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *relative: str) -> tuple[Path, Path, Path]:
    """A repository whose `core.hooksPath` holds hooks that write markers (proved live), and a slot on it on `task/tl-1`
    (`relative`: extra `git worktree add` flags, e.g. `--relative-paths`)."""
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    main, hooks, markers = tmp_path / "repo", tmp_path / "hooks", tmp_path / "markers"
    for folder in (main, hooks, markers):
        folder.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / "README").write_text("one\n")
    git(main, "add", "README")
    git(main, "commit", "-q", "-m", "base")
    for name in HOOKS:
        hook = hooks / name
        hook.write_text(f"#!/bin/sh\ntouch '{markers / name}'\n")
        hook.chmod(0o755)
    git(main, "config", "core.hooksPath", str(hooks))
    git(main, "commit", "-q", "--allow-empty", "-m", "probe")  # plain Git runs them
    assert {path.name for path in markers.iterdir()} >= {"prepare-commit-msg", "post-commit"}
    for path in markers.iterdir():
        path.unlink()
    slot = tmp_path / "slots" / "s1"
    git(main, "worktree", "add", "-q", *relative, "-b", "task/tl-1", str(slot), "HEAD")
    for path in markers.iterdir():
        path.unlink()
    return main, slot, markers


def admission(main: Path, slot: Path) -> Admission:
    key = checkouts(main).identity().key
    task = TaskReference(TaskScope("tasks"), "tl-1")
    choices = ("m", "e", "s", 100, (1, "", ""), 1, "plan")
    return Admission(AttemptKey("attempt", "dispatch", 1), task, RepoId(key), "s1", str(slot), FileRef("i", "d"), *choices)


def test_the_factory_commit_runs_no_hook_carries_the_trailer_and_leaves_the_slot_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main, slot, markers = repository(tmp_path.resolve(), monkeypatch)
    base = git(slot, "rev-parse", "HEAD").strip()
    (slot / "docs/design/tl-1").mkdir(parents=True)
    (slot / P).write_text("# Plan\n")
    attempt = admission(main, slot)
    made = settle(checkouts, RealSlotFiles(), attempt, base, ANSWER, quiet)
    assert isinstance(made, Committed) and made.sha != base
    assert clean_at(checkouts, RealSlotFiles(), attempt, made.sha) == main
    assert list(markers.iterdir()) == []  # neither --no-verify's two nor the four it leaves running
    assert git(slot, "log", "-1", "--format=%B").strip() == "Plan tl-1\n\nTask-Loop-Attempt: attempt"
    assert git(slot, "rev-parse", "HEAD^").strip() == base and git(slot, "status", "--porcelain").strip() == ""
    assert git(slot, "log", "-1", "--format=%an <%ae>").strip() == "Person <person@example.invalid>"


def test_a_symlinked_listed_path_is_unsafe_and_nothing_is_staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    main, slot, markers = repository(tmp_path.resolve(), monkeypatch)
    base = git(slot, "rev-parse", "HEAD").strip()
    (slot / "docs/design/tl-1").mkdir(parents=True)
    (slot / P).symlink_to(main / "README")
    assert settle(checkouts, RealSlotFiles(), admission(main, slot), base, ANSWER, quiet) == Unsettled("unsafe", (P,))
    assert list(markers.iterdir()) == []
    assert git(slot, "rev-parse", "HEAD").strip() == base and git(slot, "diff", "--cached", "--name-only").strip() == ""


def redirect(slot: Path, target: Path) -> None:
    """The agent's rewrite: `.git` names the real linked Git directory lexically, `L/../../../repo/.git/worktrees/s1`,
    but `L` is a symlink three levels deep inside the slot, so Git resolves it to `<slot>/repo/.git/worktrees/s1`, a
    symlink to `target`."""
    (slot / "a/b/c").mkdir(parents=True)
    (slot / "L").symlink_to(slot / "a/b/c")
    (slot / "repo/.git/worktrees").mkdir(parents=True)
    (slot / "repo/.git/worktrees/s1").symlink_to(target)
    (slot / ".git").write_text("gitdir: L/../../../repo/.git/worktrees/s1\n")


def plan(slot: Path) -> None:
    (slot / "docs/design/tl-1").mkdir(parents=True)
    (slot / P).write_text("# Plan\n")


def test_a_symlink_indirected_pointer_to_the_persons_git_directory_is_redirected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main, slot, markers = repository(tmp_path.resolve(), monkeypatch)
    base, branch = git(slot, "rev-parse", "HEAD").strip(), git(main, "rev-parse", "main").strip()
    attempt = admission(main, slot)
    plan(slot)
    redirect(slot, main / ".git")  # Git would commit the slot's files onto the person's `main`
    assert settle(checkouts, RealSlotFiles(), attempt, base, ANSWER, quiet) == Unsettled("redirected")
    assert git(main, "rev-parse", "main").strip() == branch and list(markers.iterdir()) == []


def test_a_fake_git_directory_in_the_slot_whose_filter_would_run_is_redirected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main, slot, markers = repository(tmp_path.resolve(), monkeypatch)
    base, branch = git(slot, "rev-parse", "HEAD").strip(), git(main, "rev-parse", "main").strip()
    attempt = admission(main, slot)
    plan(slot)
    fake = slot / "fake"
    git(tmp_path, "init", "-q", "--bare", str(fake))
    with (fake / "config").open("a") as config:
        config.write(f"[filter \"x\"]\n\tclean = sh -c 'touch {markers / 'filter'}; cat'\n")
    (fake / "info/attributes").write_text("* filter=x\n")
    redirect(slot, fake)
    assert settle(checkouts, RealSlotFiles(), attempt, base, ANSWER, quiet) == Unsettled("redirected")
    assert list(markers.iterdir()) == [] and git(main, "rev-parse", "main").strip() == branch
    assert git(slot, "--git-dir", str(main / ".git/worktrees/s1"), "rev-parse", "HEAD").strip() == base



class SwappedAfter(RealSlotFiles):
    """The slot file port while a process still runs in the slot: right after the `check`-th pointer check has read the
    back-pointer (that check passed), `.git` is rewritten to name `target`."""

    def __init__(self, slot: Path, target: Path, check: int) -> None:
        self.slot, self.target, self.check, self.seen = slot, target, check, 0

    def resolve(self, path: Path) -> Path | None:
        found = super().resolve(path)
        if path == self.slot / ".git":
            self.seen += 1
            if self.seen == self.check:
                (self.slot / ".git").write_text(f"gitdir: {self.target}\n")
        return found


def test_a_pointer_swapped_after_the_check_before_the_stage_does_not_change_the_git_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second pointer check (right before `stage`) passes, then `.git` names a fake Git directory whose `clean`
    filter would run outside the sandbox: `stage` still runs on the verified Git directory (the view is pinned to it),
    the filter never runs, and the check before `record` finds the swap (`redirected`, nothing committed)."""
    main, slot, markers = repository(tmp_path.resolve(), monkeypatch)
    base = git(slot, "rev-parse", "HEAD").strip()
    attempt = admission(main, slot)
    plan(slot)
    fake = tmp_path.resolve() / "fake"
    git(tmp_path, "init", "-q", "--bare", str(fake))
    git(tmp_path, "config", "--file", str(fake / "config"), "filter.x.clean", f"touch '{markers / 'filter'}' && cat")
    (fake / "info/attributes").write_text("* filter=x\n")
    files = SwappedAfter(slot, fake, check=2)
    assert settle(checkouts, files, attempt, base, ANSWER, quiet) == Unsettled("redirected")
    assert files.seen == 2 and list(markers.iterdir()) == []  # the third check fails before its back-pointer read
    verified = ("--git-dir", str(main / ".git/worktrees/s1"), "--work-tree", str(slot))
    assert git(slot, *verified, "diff", "--cached", "--name-only").strip() == P
    assert git(slot, *verified, "rev-parse", "HEAD").strip() == base

def test_a_relative_paths_worktree_is_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    main, slot, markers = repository(tmp_path.resolve(), monkeypatch, "--relative-paths")
    assert not (slot / ".git").read_text().startswith("gitdir: /")  # the pointer and its back-pointer are relative
    base = git(slot, "rev-parse", "HEAD").strip()
    plan(slot)
    made = settle(checkouts, RealSlotFiles(), admission(main, slot), base, ANSWER, quiet)
    assert isinstance(made, Committed) and git(slot, "rev-parse", "HEAD").strip() == made.sha and list(markers.iterdir()) == []


@pytest.mark.parametrize("extra", [False, True], ids=["one_trailer_commit", "two_commits"])
def test_a_crash_leftover_is_adopted_through_real_history_only_as_one_trailer_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: bool
) -> None:
    main, slot, _markers = repository(tmp_path.resolve(), monkeypatch)
    base = git(slot, "rev-parse", "HEAD").strip()
    plan(slot)
    hookless = ("-c", "core.hooksPath=/dev/null")
    if extra:
        git(slot, *hookless, "commit", "-q", "--allow-empty", "-m", "someone else")
    git(slot, *hookless, "add", P)
    git(slot, *hookless, "commit", "-q", "-m", "Plan tl-1\n\nTask-Loop-Attempt: attempt")
    head = git(slot, "rev-parse", "HEAD").strip()
    found = settle(checkouts, RealSlotFiles(), admission(main, slot), base, ANSWER, quiet)
    assert found == (Unsettled("head_moved") if extra else Committed(head))


def test_a_slot_whose_git_file_is_gone_never_reaches_an_enclosing_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A dotfiles repository at the person's home encloses the slots root. With `<slot>/.git` gone (deleted after the
    pointer check), git_porcelain pins nothing and Git would discover that repository: the ceiling stops it at the slot."""
    home = tmp_path.resolve() / "home"
    home.mkdir()
    main, slot, markers = repository(home, monkeypatch)
    git(home, "init", "-q", "-b", "dots")
    (home / ".profile").write_text("x\n")
    git(home, "add", ".profile")
    git(home, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "dotfiles")
    dots = git(home, "rev-parse", "dots").strip()
    base = git(slot, "rev-parse", "HEAD").strip()
    plan(slot)
    attempt = admission(main, slot)
    (slot / ".git").unlink()
    assert settle(checkouts, RealSlotFiles(), attempt, base, ANSWER, quiet) == Unsettled("redirected")
    view = checkouts(slot).worktree(slot)  # what a Git call after a passed check would meet
    with pytest.raises(GitUnavailable):
        view.stage([P])
    with pytest.raises(GitUnavailable):
        view.record("x", paths="all")
    assert git(home, "rev-parse", "dots").strip() == dots and list(markers.iterdir()) == []


def test_a_pointer_through_an_agent_made_symlink_is_redirected_even_to_the_right_git_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`gitdir: glink` with `glink` a symlink in the slot to the real linked Git directory: resolved, it is right, but
    the agent could retarget the link after the check, so only a path with no symlink on the way passes."""
    main, slot, markers = repository(tmp_path.resolve(), monkeypatch)
    base = git(slot, "rev-parse", "HEAD").strip()
    attempt = admission(main, slot)
    plan(slot)
    (slot / "glink").symlink_to(main / ".git/worktrees/s1")
    (slot / ".git").write_text("gitdir: glink\n")
    assert settle(checkouts, RealSlotFiles(), attempt, base, ANSWER, quiet) == Unsettled("redirected")
    assert list(markers.iterdir()) == []


def test_a_path_with_a_nul_fails_closed_without_raising(tmp_path: Path) -> None:
    files = RealSlotFiles()
    bad = tmp_path / "a\0b"
    assert (files.lstat(bad), files.read(bad, 10), files.resolve(bad)) == (None, None, None)
    slot = tmp_path / "s1"
    slot.mkdir()
    (slot / ".git").write_text("gitdir: a\0b\n")
    assert pointer(files, slot) is None


def implementing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Admission, str]:
    """An implement attempt on a slot whose branch tracks a `.gitignore` naming `.venv/` (its B)."""
    main, slot, _markers = repository(tmp_path.resolve(), monkeypatch)
    (slot / ".gitignore").write_text(".venv/\n")
    git(slot, "add", ".gitignore")
    git(slot, "commit", "-q", "--no-verify", "-m", "ignore the venv")
    return main, slot, replace(admission(main, slot), step="implement"), git(slot, "rev-parse", "HEAD").strip()


def test_an_implement_commit_deletes_and_adds_anywhere_and_an_ignored_venv_does_not_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main, slot, attempt, base = implementing(tmp_path, monkeypatch)
    (slot / ".venv/lib").mkdir(parents=True)
    (slot / ".venv/lib/x.py").write_text("installed\n")
    (slot / "README").unlink()
    (slot / "src").mkdir()
    (slot / "src/a.py").write_text("A = 1\n")
    answer = AnswerState("valid", "implemented", "commit", ("README", "src/a.py"), "Implement")
    made = settle(checkouts, RealSlotFiles(), attempt, base, answer, quiet)
    assert isinstance(made, Committed) and git(slot, "rev-parse", "HEAD^").strip() == base
    assert git(slot, "show", "--format=", "--name-status", "HEAD").split() == ["D", "README", "A", "src/a.py"]
    assert clean_at(checkouts, RealSlotFiles(), attempt, made.sha) == main


@pytest.mark.parametrize(("paths", "unsafe"), [(("gone.py",), "gone.py"), (("src/a.py",), ".gitignore")])
def test_an_absent_path_never_in_b_and_a_changed_gitignore_are_unsafe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, paths: tuple[str, ...], unsafe: str
) -> None:
    _main, slot, attempt, base = implementing(tmp_path, monkeypatch)
    (slot / "src").mkdir()
    (slot / "src/a.py").write_text("A = 1\n")
    (slot / ".gitignore").write_text(".venv/\nsrc/b.py\n")
    answer = AnswerState("valid", "implemented", "commit", paths, "Implement")
    assert settle(checkouts, RealSlotFiles(), attempt, base, answer, quiet) == Unsettled("unsafe", (unsafe,))
    assert git(slot, "rev-parse", "HEAD").strip() == base and git(slot, "diff", "--cached", "--name-only").strip() == ""


def typed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Admission, str]:
    """An implement attempt whose B holds an executable `run.sh`, a symlink `link`, a symlinked folder `lib` and a gitlink
    `sub` (its folder empty, as an uninitialised submodule)."""
    main, slot, _attempt, _base = implementing(tmp_path, monkeypatch)
    (slot / "run.sh").write_text("#!/bin/sh\n")
    (slot / "run.sh").chmod(0o755)
    (slot / "link").symlink_to("README")
    (slot / "lib").symlink_to("docs")
    git(slot, "add", "run.sh", "link", "lib")
    head = git(slot, "rev-parse", "HEAD").strip()
    git(slot, "update-index", "--add", "--cacheinfo", f"160000,{head},sub")
    (slot / "sub").mkdir()
    git(slot, "commit", "-q", "--no-verify", "-m", "typed entries")
    return main, slot, replace(admission(main, slot), step="implement"), git(slot, "rev-parse", "HEAD").strip()


def plain(slot: Path, path: str) -> None:
    """The agent's type change: the entry at `path` replaced by a plain 0644 file (a folder `lib/` for `lib/a.py`)."""
    first = slot / path.split("/", maxsplit=1)[0]
    if first.is_symlink():
        first.unlink()
    elif first.is_dir():
        first.rmdir()
    if "/" in path:
        first.mkdir()
    (slot / path).write_text("plain\n")
    (slot / path).chmod(0o644)


@pytest.mark.parametrize("path", ["run.sh", "link", "sub", "lib/a.py"])
def test_a_typed_entry_of_b_replaced_by_a_plain_file_is_unsafe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    _main, slot, attempt, base = typed(tmp_path, monkeypatch)
    plain(slot, path)
    answer = AnswerState("valid", "implemented", "commit", (path,), "Implement")
    assert settle(checkouts, RealSlotFiles(), attempt, base, answer, quiet) == Unsettled("unsafe", (path,))
    assert git(slot, "rev-parse", "HEAD").strip() == base and git(slot, "diff", "--cached", "--name-only").strip() == ""


@pytest.mark.parametrize("path", ["run.sh", "link", "sub"])
def test_the_verdict_rejects_a_type_change_to_a_plain_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    """Committed behind the factory's back: the diff reports it as a change; B's entry was not a plain file."""
    main, slot, _attempt, base = typed(tmp_path, monkeypatch)
    plain(slot, path)
    if path == "sub":
        git(slot, "rm", "-q", "--cached", "sub")
    git(slot, "add", path)
    git(slot, "commit", "-q", "--no-verify", "-m", "type change")
    x = git(slot, "rev-parse", "HEAD").strip()
    link = ChainLink(1, base, x, "commit", (path,), FileRef("i", "d"))
    assert judge(checkouts(main), main, x, IMPLEMENT, IMPLEMENT.rules("tl-1"), (link,)) == Rejected("mode")
