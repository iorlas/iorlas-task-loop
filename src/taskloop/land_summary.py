"""The land's commit message and summary (tl-8bh9.14.8 sections 9 and 10), from typed values, never from logs.

**The message** of S: the tracker's title and the task id as the subject, the branch's commit subjects (X's commits not on
O, which is merge-base(O, X)..X, oldest first, at most `SUBJECTS` lines), then the trailers `Task:`, `Plan:` (when the
plan file exists at X) and `Checked:`. Every text from outside (the title, each subject, the task id) is one line:
control, format and line-separator characters become spaces, so no title or subject can add a line, a paragraph or a
trailer; the trailers are always the message's last paragraph and only the factory writes them. No co-author trailer:
author and committer are the person (their Git identity); the task branch keeps the agent's commits.

**The summary** (`--summary`): facts, no judgment. The checks attempt for exactly X with each required name's result; the
required names at O against the checks attempt's; each required check whose argv at X differs from its argv at O; checks
added, removed or changed at X against O and a changed `setup`; every changed check-configuration file between
merge-base(O, X) and X (by tree listings); O and whether S's tree is X's, a conflict's paths, or no change; the message
and the diff command. `lines` renders it, every outside text shown printable.
"""

import shlex
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from git_porcelain import Conflicted, GitUnavailable, MissingRevision, Repo, Sha, Squashed

from taskloop.check_store import ChecksRow, Required, ResultRow
from taskloop.operations import Failed
from taskloop.profile import Argv, Check, Profile, ProfileFiles, Refused, Unavailable, read_profile

TITLE: Final = 72  # a title's and a listed subject's characters
SUBJECTS: Final = 50  # listed commit subjects, then `- ... and <n> more`
CONFLICTS: Final = 20  # listed conflicted paths
CONFIG: Final = frozenset({".task-loop.json", "justfile", "pyproject.toml", "uv.lock", "mise.toml", ".importlinter"})
type Files = Mapping[str, tuple[str, Sha]]
type State = Literal["same_tree", "moved", "conflict", "no_change"]


def one_line(text: str, cap: int) -> str:
    """`text` as one printable line of at most `cap` characters: every control, format, surrogate, private-use or
    unassigned character becomes a space, then every run of whitespace (line and paragraph separators included) one."""
    kept = "".join(" " if unicodedata.category(char).startswith("C") else char for char in text)
    return " ".join(kept.split())[:cap].rstrip()


def commits(repo: Repo, o: str, x: str) -> tuple[tuple[str, str], ...]:
    """The branch's commits, X's not on O, oldest first: (sha, subject)."""
    return tuple((entry.sha, entry.subject) for entry in reversed(repo.history([x], not_on=[o])))


def message(title: str, checks: ChecksRow, listed: Sequence[tuple[str, str]], plan: bool) -> str:
    """S's commit message (section 9)."""
    task, x = one_line(checks.task_id, TITLE), checks.commit
    head = one_line(title, TITLE) or "Untitled task"
    lines = [f"- {one_line(subject, TITLE) or '(no subject)'} ({sha[:12]})" for sha, subject in listed[:SUBJECTS]]
    lines += [f"- ... and {len(listed) - SUBJECTS} more"] if len(listed) > SUBJECTS else []
    squashed = [f"Squashed from task/{task} at {x}:", *lines] if lines else [f"Squashed from task/{task} at {x}."]
    trailers = [f"Task: {task}", *([f"Plan: {plan_path(task)}"] if plan else []),
                f"Checked: {checks.key.attempt_id} {checks.conclusion or 'unconcluded'} at {x}"]
    return "\n".join([f"{head} ({task})", "", *squashed, "", *trailers]) + "\n"


def plan_path(task_id: str) -> str:
    return f"docs/design/{task_id}/plan.md"


def message_at(repo: Repo, title: str, checks: ChecksRow, o: str) -> str:
    """The message read from Git: the branch's subjects and whether the plan file exists at X."""
    tree = repo.tree(f"{checks.commit}^{{commit}}")
    plan = tree is not None and plan_path(one_line(checks.task_id, TITLE)) in tree.files
    return message(title, checks, commits(repo, o, checks.commit), plan)


@dataclass(frozen=True)
class Changed:
    """One check at O and at X (None: absent there)."""

    name: str
    at_o: Check | None
    at_x: Check | None


@dataclass(frozen=True)
class LandSummary:
    """Section 10's facts. `results`: each name the checks attempt required with its latest-block conclusion; `added` and
    `removed`: required at O and not by the checks attempt, and the reverse; `argv`: required at O with another argv at X;
    `checks`: every check added, removed or changed at X; `setup`: (at O, at X) when changed; `files`: changed check
    configuration; `base`: merge-base(O, X)."""

    checks_id: str
    conclusion: str | None
    target: str
    x: str
    results: tuple[tuple[str, str], ...]
    origin: str
    added: tuple[str, ...]
    removed: tuple[str, ...]
    argv: tuple[Changed, ...]
    checks: tuple[Changed, ...]
    setup: tuple[tuple[Argv, ...], tuple[Argv, ...]] | None
    files: tuple[str, ...]
    base: str
    state: State
    conflicts: tuple[str, ...]
    message: str

    @property
    def again(self) -> bool:
        """The land validates S: its tree is not X's, or the required names changed."""
        return self.state == "moved" or (self.state == "same_tree" and bool(self.added or self.removed))


def _changed(at_o: Profile, at_x: Profile) -> tuple[Changed, ...]:
    """Checks added, removed or changed (argv or timeout) at X against O, by name."""
    before, after = {check.name: check for check in at_o.checks}, {check.name: check for check in at_x.checks}
    names = sorted(before.keys() | after.keys())
    return tuple(Changed(name, before.get(name), after.get(name)) for name in names if before.get(name) != after.get(name))


def _named(at_x: Profile, tree_x: Files) -> set[str]:
    """Tracked files a check's or `setup`'s argv at X names: an element that is a file, or a folder holding files, in X
    (an option, `.`, an absolute or `..` path names none: X's tree paths are relative and normalized)."""
    found: set[str] = set()
    for argv in (*at_x.setup, *(check.argv for check in at_x.checks)):
        for element in argv:
            path = element.removeprefix("./").rstrip("/")
            found.update(each for each in tree_x if each == path or each.startswith(f"{path}/"))
    return found


def config_files(base: Files, tree_x: Files, at_x: Profile) -> tuple[str, ...]:
    """Every check-configuration file changed between merge-base(O, X) and X (section 10 item 5)."""
    changed = {path for path in base.keys() | tree_x.keys() if base.get(path) != tree_x.get(path)}
    named = _named(at_x, tree_x)
    return tuple(sorted(path for path in changed if path in CONFIG or path.startswith("tests/rules/")
                        or path.rsplit("/", 1)[-1] == "conftest.py" or path in named))


@dataclass(frozen=True)
class Trees:
    """The tree listings the summary compares: merge-base(O, X) and its commit, X, O, and S (None: a conflict)."""

    base: str
    at_base: Files
    x: Files
    o: Files
    s: Files | None


def summary(checks: ChecksRow, results: Sequence[ResultRow], profiles: tuple[Profile, Profile], required_o: Required,
            made: Squashed | Conflicted, trees: Trees, text: str, o: str) -> LandSummary:
    """Section 10's facts from the checks attempt, its latest block's results, the profiles at O and X, the required names
    at O, the squash and the tree listings."""
    at_o, at_x = profiles
    concluded = {row.name: row.conclusion or "unfinished" for row in results}
    names_o, names_c = [name for name, _ in required_o], [name for name, _ in checks.required]
    argv_x = {check.name: check for check in at_x.checks}
    argv_o = {check.name: check for check in at_o.checks}
    argv = tuple(Changed(name, argv_o.get(name), argv_x.get(name)) for name in names_o
                 if (argv_o[name].argv if name in argv_o else None) != (argv_x[name].argv if name in argv_x else None))
    state: State = "conflict" if trees.s is None else "no_change" if trees.s == trees.o else "same_tree" if trees.s == trees.x \
        else "moved"
    return LandSummary(
        checks.key.attempt_id, checks.conclusion, checks.target, checks.commit,
        tuple((name, concluded.get(name, "no result")) for name in names_c), o,
        tuple(name for name in names_o if name not in names_c), tuple(name for name in names_c if name not in names_o), argv,
        _changed(at_o, at_x), None if at_o.setup == at_x.setup else (at_o.setup, at_x.setup),
        config_files(trees.at_base, trees.x, at_x), trees.base, state,
        made.paths if isinstance(made, Conflicted) else (), text)


def _listing(repo: Repo, rev: str) -> Files:
    tree = repo.tree(f"{rev}^{{commit}}")
    if tree is None:
        raise MissingRevision(rev)
    return dict(tree.files)


def summarized(repo: Repo, files: ProfileFiles, checks: ChecksRow, results: Sequence[ResultRow], made: Squashed | Conflicted,
               title: str, origin: tuple[str, Required]) -> LandSummary | Failed:
    """The summary read from Git: the profiles at O and X, merge-base(O, X), the tree listings, the message."""
    o, x = origin[0], checks.commit
    at_o, at_x = read_profile(files, o), read_profile(files, x)
    for rev, bad in ((o, at_o), (x, at_x)):
        if isinstance(bad, (Refused, Unavailable)):
            kind = "refused" if isinstance(bad, Refused) else "unavailable"
            return Failed(kind, "profile" if kind == "refused" else "git", f"The profile at {rev}: {bad.detail}")
    if not isinstance(at_o, Profile) or not isinstance(at_x, Profile):
        return Failed("unavailable", "git")
    try:
        base = repo.merge_base(o, x) or o
        trees = Trees(base, _listing(repo, base), _listing(repo, x), _listing(repo, o),
                      None if isinstance(made, Conflicted) else _listing(repo, made.sha))
        text = message_at(repo, title, checks, o)
    except (GitUnavailable, MissingRevision) as error:
        return Failed("unavailable", "git", f"Git could not read the land's commits ({type(error).__name__}): rerun.")
    return summary(checks, results, (at_o, at_x), origin[1], made, trees, text, o)


def _argv(argv: Argv | None) -> str:
    return "(none)" if argv is None else one_line(shlex.join(argv), 400)


def _check(check: Check | None) -> str:
    return "(none)" if check is None else f"{_argv(check.argv)} ({check.timeout} s)"


def _state(found: LandSummary) -> str:
    if found.state == "conflict":
        shown = ", ".join(one_line(path, 200) for path in found.conflicts[:CONFLICTS])
        return f"conflict ({len(found.conflicts)} paths): {shown}"
    if found.state == "no_change":
        return "no change: main already holds X's changes (`--no-change` records it)"
    return "same tree as X" + (", checks run again: the required names changed" if found.again else ", no checks") \
        if found.state == "same_tree" else "merged onto a moved main: checks run again"


def lines(found: LandSummary) -> tuple[str, ...]:
    """The summary as printed: one fact per line, every outside text printable."""
    names = "same" if not (found.added or found.removed) else "; ".join(
        part for part in (f"added {', '.join(found.added)}" if found.added else "",
                          f"removed {', '.join(found.removed)}" if found.removed else "") if part) + " (the checks run again)"
    setup = [] if found.setup is None else [
        f"Setup changed: {'; '.join(_argv(argv) for argv in found.setup[0]) or '(none)'} -> "
        f"{'; '.join(_argv(argv) for argv in found.setup[1]) or '(none)'}"]
    return (
        f"Checks: {found.checks_id} {found.conclusion or 'unconcluded'} at X {found.x} (main at {found.target})",
        *(f"Check: {name} {result}" for name, result in found.results),
        f"Required at origin main {found.origin}: {names}",
        *(f"Argv changed: {each.name}: {_argv(None if each.at_o is None else each.at_o.argv)} -> "
          f"{_argv(None if each.at_x is None else each.at_x.argv)}" for each in found.argv),
        *(f"Check {'added' if each.at_o is None else 'removed' if each.at_x is None else 'changed'}: {each.name}: "
          f"{_check(each.at_o)} -> {_check(each.at_x)}" for each in found.checks),
        *setup,
        *(f"Configuration changed: {one_line(path, 200)}" for path in found.files),
        f"Origin main: {found.origin}; {_state(found)}",
        "Message:", *(f"  {line}" for line in found.message.splitlines()),
        f"Diff: git diff {found.base}..{found.x}",
    )
