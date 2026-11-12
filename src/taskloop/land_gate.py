"""What a land changes in the gate that decides a pass (tl-8bh9.14.42 and .43), read from Git objects as O (origin's `main`)
and S (the squash that would land) and shared by `--summary` and the land itself: the land refuses an S whose gate facts
are not empty unless the person passes `--accept-gate-changes`, naming each fact, so a task cannot disarm the checks of
every later task unseen.

The facts, all between O and S: every changed file with its diffstat; each check added, removed or changed (argv or
timeout) and a changed `setup` or `required` list of `.task-loop.json`; each changed *configuration file* by one short
rule (`configuration`); and each changed test module that was *weakened* (`weakened`). Nothing is derived from what a
check reads: a name list of tools would always lag the next tool, so the rule is by shape. A weakened test is found by
parsing the module with `ast` at O and at S, never by reading text.
"""

import ast
import io
import tokenize
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final

from git_porcelain import Change, GitUnavailable, MissingRevision

from taskloop.land_push import Origin
from taskloop.operations import Failed
from taskloop.profile import Argv, Check, Profile, ProfileFiles, Refused, read_profile

DOCS: Final = frozenset({".md", ".rst", ".txt"})
TOOL_SUFFIXES: Final = frozenset({".toml", ".ini", ".cfg"})  # a tool's configuration at any depth (`src/ruff.toml`, `tests/pytest.ini`)
SKIPS: Final = frozenset({"skip", "skipif", "xfail", "importorskip"})  # `pytest.mark.skip`, `skip()` after `from pytest import skip`
FILES: Final = 50  # changed files listed, then `... and <n> more`
ACCEPT: Final = "--accept-gate-changes"


@dataclass(frozen=True)
class Changed:
    """One check at O and at S (None: absent there)."""

    name: str
    at_o: Check | None
    at_x: Check | None


@dataclass(frozen=True)
class Weakened:
    path: str
    why: str


@dataclass(frozen=True)
class Gate:
    """`changes`: every file S changes against O; `checks`: checks added, removed or changed; `setup` and `required`:
    (at O, at S) when changed; `configs`: changed configuration files; `weakened`: changed test modules with fewer tests or
    assertions, more skip/xfail markers, deleted or unreadable."""

    changes: tuple[Change, ...]
    checks: tuple[Changed, ...]
    setup: tuple[tuple[Argv, ...], tuple[Argv, ...]] | None
    required: tuple[tuple[str, ...], tuple[str, ...]] | None
    configs: tuple[str, ...]
    weakened: tuple[Weakened, ...]

    @property
    def decisive(self) -> bool:
        """Something that decides a pass changes: the land needs the person's acceptance."""
        return bool(self.checks or self.setup or self.required or self.configs or self.weakened)


def configuration(path: str, named: frozenset[str]) -> bool:
    """The short rule: a file at the repository root that is not documentation (`ruff.toml`, `pyproject.toml`, `justfile`,
    `.task-loop.json`, `uv.lock`, ...), a `.toml`, `.ini` or `.cfg` file at any depth, any `conftest.py`, or a file a check's
    or `setup`'s argv names."""
    pure = PurePosixPath(path)
    return (len(pure.parts) == 1 and pure.suffix not in DOCS) or pure.suffix in TOOL_SUFFIXES or pure.name == "conftest.py" \
        or path in named


def _named(profile: Profile, paths: frozenset[str]) -> frozenset[str]:
    """Tracked files an argv element names: the file itself or a folder holding files (an option, `.`, an absolute or `..`
    path names none)."""
    found: set[str] = set()
    for argv in (*profile.setup, *(check.argv for check in profile.checks)):
        for element in argv:
            path = element.removeprefix("./").rstrip("/")
            found.update(each for each in paths if each == path or each.startswith(f"{path}/"))
    return frozenset(found)


def _is_test(path: str) -> bool:
    pure = PurePosixPath(path)
    return pure.suffix == ".py" and (pure.name.startswith("test_") or pure.stem.endswith("_test") or "tests" in pure.parts[:-1])


def _noqa(source: bytes) -> int:
    """File-level `# ruff: noqa` comments (they switch rules off for the whole module)."""
    try:
        return sum(1 for token in tokenize.tokenize(io.BytesIO(source).readline)
                   if token.type == tokenize.COMMENT and token.string.lower().replace(" ", "").startswith("#ruff:noqa"))
    except (tokenize.TokenError, SyntaxError):
        return 0


def _shape(source: bytes | None) -> tuple[int, int, int] | None:
    """(test functions, assert statements, skip/xfail/`ruff: noqa` markers) of one test module; None when it does not parse."""
    try:
        tree = ast.parse(source or b"")
    except (SyntaxError, ValueError):
        return None
    tests = asserts = skips = 0
    for node in ast.walk(tree):
        tests += isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")
        asserts += isinstance(node, ast.Assert)
        skips += (isinstance(node, ast.Attribute) and node.attr in SKIPS) or (isinstance(node, ast.Name) and node.id in SKIPS)
    return tests, asserts, skips + _noqa(source or b"")


def _weakened(change: Change, before: bytes | None, after: bytes | None) -> Weakened | None:
    if change.kind == "D":
        return Weakened(change.path, "deleted")
    o, s = _shape(before), _shape(after)
    if s is None:
        return Weakened(change.path, "does not parse")
    if o is None or change.kind == "A":
        return None
    for index, what in enumerate(("tests", "assertions")):
        if s[index] < o[index]:
            return Weakened(change.path, f"{what} {o[index]} -> {s[index]}")
    return Weakened(change.path, f"skip, xfail or noqa markers {o[2]} -> {s[2]}") if s[2] > o[2] else None


def _changed(at_o: Profile, at_s: Profile) -> tuple[Changed, ...]:
    before, after = {check.name: check for check in at_o.checks}, {check.name: check for check in at_s.checks}
    return tuple(Changed(name, before.get(name), after.get(name)) for name in sorted(before.keys() | after.keys())
                 if before.get(name) != after.get(name))


def gate_of(origin: Origin, files: ProfileFiles, o: str, s: str) -> Gate | Failed:
    """The gate facts of S against O; `profile` when S's `.task-loop.json` is refused, `unavailable git` when Git cannot
    answer."""
    try:
        at_o, at_s = read_profile(files, o), read_profile(files, s)
        for rev, bad in ((s, at_s), (o, at_o)):
            if isinstance(bad, Refused):
                return Failed("refused", "profile", f"The profile at {'S' if rev == s else 'origin main'} ({rev}): {bad.detail}")
        if not isinstance(at_s, Profile) or not isinstance(at_o, Profile):
            return Failed("unavailable", "git", "The profiles at O and S could not be read: rerun.")
        tree_o, tree_s = origin.repo.tree(f"{o}^{{commit}}"), origin.repo.tree(f"{s}^{{commit}}")
        if tree_o is None or tree_s is None:
            raise MissingRevision(s)
        changes = origin.repo.worktree(origin.checkout).diff(o, s, cap=0).changes
        named = _named(at_s, frozenset(tree_s.files))
        flagged = (_weakened(each, tree_o.read(each.path), tree_s.read(each.path)) for each in changes if _is_test(each.path))
        return Gate(changes, _changed(at_o, at_s), None if at_o.setup == at_s.setup else (at_o.setup, at_s.setup),
                    None if at_o.required == at_s.required else (at_o.required, at_s.required),
                    tuple(each.path for each in changes if configuration(each.path, named)),
                    tuple(found for found in flagged if found is not None))
    except (GitUnavailable, MissingRevision) as error:
        return Failed("unavailable", "git", f"Git could not read the land's changes ({type(error).__name__}): rerun.")
