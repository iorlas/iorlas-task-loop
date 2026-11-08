"""The ratchets without a stored baseline: each judges the change, not the tree.

Design. layer_ratchet, temp_ratchet and needs_ratchet used to compare today's counts with a JSON file every PR rewrote, so two PRs in
different areas conflicted on it and one landing turned the others red. Now nothing is stored (as tests/rules/type_counts.py already
works): a ratchet counts its offenders in the .py files the change touches, at the merge base with origin/main (`git show`) and in the
working tree, per key (offender kind, or capability total for needs), and fails when a key's count went up. New needs reasons must
have at least five words and sit on one test. A move is net zero; a cleanup
needs no `--write`; two PRs that touch different files share no file. No origin/main (a bare checkout): skipped, said so.
A deliberate rise is a commit message line:
`Ratchet-allow: <temp|layer|needs|closure|effects|root> +N <a reason in words>`.
"""
import ast
import functools
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

Counter = Callable[[str, ast.Module], dict[str, int]]
ALLOW = re.compile(r"^Ratchet-allow:\s+(\w+)\s+\+(\d+)\s+(\S.*)$", re.MULTILINE)
MIN_REASON_WORDS = 4


def git(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True, check=False)


def merge_base(root: Path, ref: str = "origin/main") -> str | None:
    ran = git(root, "merge-base", "HEAD", ref)
    return ran.stdout.strip() if ran.returncode == 0 else None


def changed_py(root: Path, base: str) -> list[str]:
    """The .py files the change adds, modifies, deletes or renames against `base`, plus untracked ones."""
    names = set(git(root, "diff", "--name-only", "--no-renames", base).stdout.split())
    names |= set(git(root, "ls-files", "--others", "--exclude-standard").stdout.split())
    return sorted(n for n in names if n.endswith(".py"))


def tree_of(text: str | None) -> ast.Module | None:
    try:
        return ast.parse(text) if text is not None else None
    except SyntaxError:
        return None


def counted(counter: Counter, rel: str, text: str | None) -> dict[str, int]:
    tree = tree_of(text)
    return counter(rel, tree) if tree is not None else {}


@functools.cache
def texts_at(root: Path, base: str, paths: tuple[str, ...]) -> dict[str, str | None]:
    """{path: its text at `base`, or None if it did not exist}: one `git cat-file --batch` for all of them, not a `git show` each (a change
    that moves a thousand files costs one process, not five thousand: every ratchet reads the same texts)."""
    ran = subprocess.run(["git", "-C", str(root), "cat-file", "--batch"], input="".join(f"{base}:{p}\n" for p in paths).encode(),
                         capture_output=True, check=False)
    out: dict[str, str | None] = {}
    data, at = ran.stdout, 0
    for rel in paths:
        end = data.index(b"\n", at)
        head = data[at:end].split()
        at = end + 1
        if len(head) == 3 and head[1] == b"blob":
            size = int(head[2])
            out[rel] = data[at:at + size].decode("utf-8", errors="replace")
            at += size + 1
        else:
            out[rel] = None
    return out


def net(counter: Counter, root: Path, base: str, paths: list[str], *,
        counter_at: Callable[[str | None], Counter] | None = None) -> tuple[dict[str, int], dict[str, int]]:
    """(before, after): the counter's totals per key over `paths` at `base` and in the working tree."""
    before: dict[str, int] = {}
    after: dict[str, int] = {}
    olds = texts_at(root, base, (*paths, ".importlinter") if counter_at else tuple(paths))
    base_counter = counter_at(olds[".importlinter"]) if counter_at else counter
    for rel in paths:
        mine = root / rel
        now = mine.read_text(encoding="utf-8") if mine.is_file() else None
        for out, text, side_counter in ((before, olds[rel], base_counter), (after, now, counter)):
            for key, n in counted(side_counter, rel, text).items():
                out[key] = out.get(key, 0) + n
    return before, after


def rises(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {k: n - before.get(k, 0) for k, n in sorted(after.items()) if n > before.get(k, 0)}


def allowed(root: Path, base: str, ratchet: str) -> int:
    """The total of `Ratchet-allow: <ratchet> +N reason` lines in the change's commit messages (a reason in words, else it counts 0)."""
    log = git(root, "log", "--format=%B", f"{base}..HEAD").stdout
    return sum(int(n) for name, n, reason in ALLOW.findall(log) if name == ratchet and len(reason.split()) >= MIN_REASON_WORDS)


def grouped(counts: dict[str, int], group: Callable[[str], str]) -> dict[str, int]:
    """Sum counts under the keys supplied by group."""
    out: dict[str, int] = {}
    for key, n in counts.items():
        name = group(key)
        out[name] = out.get(name, 0) + n
    return out


def problems(ratchet: str, counter: Counter, root: Path, *,
             counter_at: Callable[[str | None], Counter] | None = None,
             group: Callable[[str], str] | None = None) -> list[str] | None:
    """The keys that rose beyond what the change allows, or None when there is no origin/main to compare with."""
    base = merge_base(root)
    if base is None:
        return None
    before, after = net(counter, root, base, changed_py(root, base), counter_at=counter_at)
    if group is not None:
        before, after = grouped(before, group), grouped(after, group)
    up = rises(before, after)
    if sum(up.values()) <= allowed(root, base, ratchet):
        return []
    return [f"{key}: +{n}" for key, n in up.items()]
