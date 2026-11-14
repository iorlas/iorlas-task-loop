"""The land's commit message and summary (tl-8bh9.14.8 sections 9 and 10), from typed values, never from logs.

**The message** of S: the tracker's title and the task id as the subject, the branch's commit subjects (X's commits not on
O, which is merge-base(O, X)..X, oldest first, at most `SUBJECTS` lines), then the trailers `Task:`, `Plan:` (when the
plan file exists at X) and `Checked:`. Every text from outside (the title, each subject, the task id) is one line:
control, format and line-separator characters become spaces, so no title or subject can add a line, a paragraph or a
trailer; the trailers are always the message's last paragraph and only the factory writes them. No co-author trailer:
author and committer are the person (their Git identity); the task branch keeps the agent's commits.

**The summary** (`--summary`): facts, no judgment. The checks attempt for exactly X with each required name's result; the
required names at O against the checks attempt's; each required check whose argv at X differs from its argv at O; the gate
facts of S against O (`land_gate`: every changed file with its diffstat, checks, `setup` and `required` changed,
configuration files, weakened tests); O and whether S's tree is X's, a conflict's paths, or no change; the message and the
diff command. `lines` renders it, every outside text shown printable.
"""

import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from git_porcelain import Conflicted, GitUnavailable, MissingRevision, Repo, Sha, Squashed

from taskloop.check_store import ChecksRow, Required, ResultRow
from taskloop.command_conclusion import CommandConclusion, encode
from taskloop.land_gate import ACCEPT, FILES, Changed, Gate, gate_of
from taskloop.land_push import Origin
from taskloop.operations import Failed
from taskloop.printable import one_line, title_line
from taskloop.profile import Argv, Check, Profile, ProfileFiles, Refused, Unavailable, read_profile

TITLE: Final = 72  # a title's and a listed subject's characters
AUTOSQUASH: Final = frozenset({"fixup!", "squash!", "amend!", "reword!"})
SUBJECTS: Final = 50  # listed commit subjects, then `- ... and <n> more`
CONFLICTS: Final = 20  # listed conflicted paths
type Files = Mapping[str, tuple[str, Sha]]
type State = Literal["same_tree", "moved", "conflict", "no_change"]


def commits(repo: Repo, o: str, x: str) -> tuple[tuple[str, str], ...]:
    """The branch's commits, X's not on O, oldest first: (sha, subject)."""
    return tuple((entry.sha, entry.subject) for entry in reversed(repo.history([x], not_on=[o])))


def message(title: str, checks: ChecksRow, listed: Sequence[tuple[str, str]], plan: bool) -> str:
    """S's commit message (section 9)."""
    task, x = one_line(checks.task_id, TITLE), checks.commit
    head = title_line(_plain(one_line(title)) or "Untitled task", TITLE, f" ({task})")
    lines = [f"- {one_line(subject, TITLE) or '(no subject)'} ({sha[:12]})" for sha, subject in listed[:SUBJECTS]]
    lines += [f"- ... and {len(listed) - SUBJECTS} more"] if len(listed) > SUBJECTS else []
    squashed = [f"Squashed from task/{task} at {x}:", *lines] if lines else [f"Squashed from task/{task} at {x}."]
    trailers = [f"Task: {task}", *([f"Plan: {plan_path(task)}"] if plan else []),
                f"Checked: {checks.key.attempt_id} {checks.conclusion or 'unconcluded'} at {x}"]
    return "\n".join([head, "", *squashed, "", *trailers]) + "\n"


def _plain(title: str) -> str:
    """The title without leading `fixup!`, `squash!`, `amend!` or `reword!`: `git rebase --autosquash` would fold S into
    another commit (only the title is the person's; the task id suffix stays)."""
    while (word := title.split(" ", 1)[0].lower()) in AUTOSQUASH:
        title = title[len(word):].lstrip()
    return title


def plan_path(task_id: str) -> str:
    return f"docs/design/{task_id}/plan.md"


def message_at(repo: Repo, title: str, checks: ChecksRow, o: str) -> str:
    """The message read from Git: the branch's subjects and whether the plan file exists at X."""
    tree = repo.tree(f"{checks.commit}^{{commit}}")
    plan = tree is not None and plan_path(one_line(checks.task_id, TITLE)) in tree.files
    return message(title, checks, commits(repo, o, checks.commit), plan)


@dataclass(frozen=True)
class LandSummary:
    """Section 10's facts. `results`: each name the checks attempt required with its latest-block conclusion; `added` and
    `removed`: required at O and not by the checks attempt, and the reverse; `argv`: required at O with another argv at X;
    `gate`: what S changes in the gate against O (None for a conflict: no S); `base`: merge-base(O, X)."""

    checks_id: str
    conclusion: str | None
    target: str
    x: str
    results: tuple[tuple[str, CommandConclusion | Literal["unfinished", "no result"]], ...]
    origin: str
    added: tuple[str, ...]
    removed: tuple[str, ...]
    argv: tuple[Changed, ...]
    gate: Gate | None
    base: str
    state: State
    conflicts: tuple[str, ...]
    message: str

    @property
    def again(self) -> bool:
        """The land validates S: its tree is not X's, or the required names changed."""
        return self.state == "moved" or (self.state == "same_tree" and bool(self.added or self.removed))


@dataclass(frozen=True)
class Trees:
    """The tree listings the summary compares: merge-base(O, X), X, O, and S (None: a conflict)."""

    base: str
    x: Files
    o: Files
    s: Files | None


def summary(checks: ChecksRow, results: Sequence[ResultRow], profiles: tuple[Profile, Profile], required_o: Required,
            made: Squashed | Conflicted, trees: Trees, text: tuple[str, Gate | None], o: str) -> LandSummary:
    """Section 10's facts from the checks attempt, its latest block's results, the profiles at O and X, the required names
    at O, the squash, the tree listings, and the message with the gate facts."""
    at_o, at_x = profiles
    concluded: dict[str, CommandConclusion | Literal["unfinished", "no result"]] = {
        row.name: row.conclusion or "unfinished" for row in results}

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
        text[1], trees.base, state, made.paths if isinstance(made, Conflicted) else (), text[0])


def _listing(repo: Repo, rev: str) -> Files:
    tree = repo.tree(f"{rev}^{{commit}}")
    if tree is None:
        raise MissingRevision(rev)
    return dict(tree.files)


def summarized(repo: Origin, files: ProfileFiles, checks: ChecksRow, results: Sequence[ResultRow], made: Squashed | Conflicted,
               title: str, origin: tuple[str, Required]) -> LandSummary | Failed:
    """The summary read from Git: the profiles at O and X, merge-base(O, X), the tree listings, the message, the gate."""
    o, x = origin[0], checks.commit
    at_o, at_x = read_profile(files, o), read_profile(files, x)
    for rev, bad in ((o, at_o), (x, at_x)):
        if isinstance(bad, (Refused, Unavailable)):
            kind = "refused" if isinstance(bad, Refused) else "unavailable"
            return Failed(kind, "profile" if kind == "refused" else "git", f"The profile at {rev}: {bad.detail}")
    if not isinstance(at_o, Profile) or not isinstance(at_x, Profile):
        return Failed("unavailable", "git")
    try:
        base = repo.repo.merge_base(o, x) or o
        trees = Trees(base, _listing(repo.repo, x), _listing(repo.repo, o),
                      None if isinstance(made, Conflicted) else _listing(repo.repo, made.sha))
        text = message_at(repo.repo, title, checks, o)
    except (GitUnavailable, MissingRevision) as error:
        return Failed("unavailable", "git", f"Git could not read the land's commits ({type(error).__name__}): rerun.")
    gate = None if isinstance(made, Conflicted) else gate_of(repo, files, o, made.sha)
    return gate if isinstance(gate, Failed) else summary(checks, results, (at_o, at_x), origin[1], made, trees, (text, gate), o)


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
    return (
        f"Checks: {found.checks_id} {found.conclusion or 'unconcluded'} at X {found.x} (main at {found.target})",
        *(f"Check: {name} {encode(result) if isinstance(result, CommandConclusion) else result}" for name, result in found.results),
        f"Required at origin main {found.origin}: {names}",
        *(f"Argv changed: {each.name}: {_argv(None if each.at_o is None else each.at_o.argv)} -> "
          f"{_argv(None if each.at_x is None else each.at_x.argv)}" for each in found.argv),
        *([] if found.gate is None else gate_lines(found.gate)),
        f"Origin main: {found.origin}; {_state(found)}",
        "Message:", *(f"  {line}" for line in found.message.splitlines()),
        f"Diff: git diff {found.base}..{found.x}",
    )


def _joined(setup: tuple[Argv, ...]) -> str:
    return "; ".join(_argv(argv) for argv in setup) or "(none)"


def gate_lines(gate: Gate) -> list[str]:
    """The gate facts as printed (`--summary` and the refusal of a land that needs `--accept-gate-changes`): every changed
    file with its diffstat, then each fact that decides a pass, every outside text printable."""
    added, deleted = sum(each.added for each in gate.changes), sum(each.deleted for each in gate.changes)
    shown = [f"  {each.kind} {one_line(each.path, 200)} +{each.added} -{each.deleted}" for each in gate.changes[:FILES]]
    more = [f"  ... and {len(gate.changes) - FILES} more"] if len(gate.changes) > FILES else []
    return [
        f"Files changed: {len(gate.changes)} (+{added} -{deleted})", *shown, *more,
        *(f"Check {'added' if each.at_o is None else 'removed' if each.at_x is None else 'changed'}: {each.name}: "
          f"{_check(each.at_o)} -> {_check(each.at_x)}" for each in gate.checks),
        *([] if gate.setup is None else [f"Setup changed: {_joined(gate.setup[0])} -> {_joined(gate.setup[1])}"]),
        *([] if gate.required is None else [f"Required changed: {', '.join(gate.required[0]) or '(none)'} -> "
                                              f"{', '.join(gate.required[1]) or '(none)'}"]),
        *(f"Configuration changed: {one_line(path, 200)}" for path in gate.configs),
        *(f"Test weakened: {one_line(each.path, 200)}: {each.why}" for each in gate.weakened),
        *([f"These change what decides a pass: rerun `tl step land` with {ACCEPT} to land them (a test module split, or its "
           "assertions merged, shows as weakened and is accepted the same way)."] if gate.decisive else []),
    ]
