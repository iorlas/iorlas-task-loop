"""FakeGit's reads over trees: status, unified diff, numstat, and whole-word grep.

The diff is git's format for the common case (headers, ``index`` abbreviations, hunks with three lines of
context and the function-name suffix on the ``@@`` line). It does no rename detection and uses difflib's
alignment, so unusual edits can pair lines differently from git's.
"""

from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING, NamedTuple

from git_porcelain.fake_store import blob_sha
from git_porcelain.porcelain import StatusEntry

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from git_porcelain.fake_ignore import Ignore
    from git_porcelain.fake_store import CheckoutState, Store

__all__ = ["Stat", "diff_stat", "diff_text", "grep_files", "status_entries"]


class Stat(NamedTuple):
    path: str
    added: int
    deleted: int


_ZERO = "0" * 7
_FUNC = re.compile(r"^[A-Za-z_$]")
_NO_EOL = "\n\\ No newline at end of file"


def status_entries(head: Mapping[str, str], wt: CheckoutState, ignore: Ignore) -> list[StatusEntry]:
    """``git status --porcelain=v1 -uall``: tracked changes by path, then untracked files by path."""
    staged = {p: _x(head.get(p), wt.index.get(p)) for p in sorted(set(head) | set(wt.index))}
    renames = _renames(head, wt.index, staged)
    entries: list[StatusEntry] = []
    for path in sorted(set(head) | set(wt.index)):
        data = wt.files.get(path)
        if path in wt.unmerged:
            entries.append(StatusEntry("UU", path))
            continue
        y = " " if path not in wt.index else ("D" if data is None else ("M" if blob_sha(data) != wt.index[path] else " "))
        x = staged[path]
        if x == "D" and path in renames.values():
            continue
        if x == "A" and path in renames:
            entries.append(StatusEntry("R" + y, path, renames[path]))
        elif x + y != "  ":
            entries.append(StatusEntry(x + y, path))
    entries.sort(key=lambda e: e.path)
    entries += [StatusEntry("??", p) for p in sorted(wt.files) if p not in wt.index and not ignore.ignores(p)]
    return entries


def _x(old: str | None, new: str | None) -> str:
    if old is None and new is not None:
        return "A"
    if old is not None and new is None:
        return "D"
    return " " if old == new else "M"


def _renames(head: Mapping[str, str], index: Mapping[str, str], staged: Mapping[str, str]) -> dict[str, str]:
    """New path to old path for each staged addition whose content equals a staged deletion."""
    gone = {head[p]: p for p, x in sorted(staged.items()) if x == "D"}
    found: dict[str, str] = {}
    for path, x in sorted(staged.items()):
        if x == "A" and index[path] in gone:
            found[path] = gone.pop(index[path])
    return found


def _text_lines(data: bytes) -> list[str]:
    text = data.decode("utf-8", "replace")
    if not text:
        return []
    parts = text.split("\n")
    if parts[-1] == "":
        return parts[:-1]
    parts[-1] += _NO_EOL
    return parts


def _hunks(old: list[str], new: list[str], path: str, *, added: bool, deleted: bool) -> list[str]:
    out = list(
        difflib.unified_diff(old, new, "/dev/null" if added else f"a/{path}", "/dev/null" if deleted else f"b/{path}", n=3, lineterm="")
    )
    result: list[str] = []
    for line in out:
        if line.startswith("@@"):
            start = int(line.split()[1].lstrip("-").split(",")[0])
            result.append(line + _context(old, start))
        else:
            result.append(line)
    return result


def _context(old: list[str], start: int) -> str:
    for line in reversed(old[: max(start - 1, 0)]):
        if _FUNC.match(line):
            return " " + line.removesuffix(_NO_EOL).rstrip()[:80]
    return ""


def _file_diff(path: str, old: str | None, new: str | None, store: Store) -> str:
    before = store.blobs[old] if old else b""
    after = store.blobs[new] if new else b""
    head = [f"diff --git a/{path} b/{path}"]
    if old is None:
        head += ["new file mode 100644", f"index {_ZERO}..{(new or '')[:7]}"]
    elif new is None:
        head += ["deleted file mode 100644", f"index {old[:7]}..{_ZERO}"]
    else:
        head.append(f"index {old[:7]}..{new[:7]} 100644")
    if b"\0" in before + after:
        return (
            "\n".join(
                [
                    *head,
                    f"Binary files {'/dev/null' if old is None else 'a/' + path} and {'/dev/null' if new is None else 'b/' + path} differ",
                ]
            )
            + "\n"
        )
    hunks = _hunks(_text_lines(before), _text_lines(after), path, added=old is None, deleted=new is None)
    return "\n".join([*head, *hunks]) + "\n"


def _kept(path: str, exclude: Sequence[str]) -> bool:
    return not any(path == e or path.startswith(e.rstrip("/") + "/") for e in exclude)


def diff_text(a: Mapping[str, str], b: Mapping[str, str], store: Store, exclude: Sequence[str] = ()) -> str:
    paths = sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p) and _kept(p, exclude))
    return "".join(_file_diff(p, a.get(p), b.get(p), store) for p in paths)


def diff_stat(a: Mapping[str, str], b: Mapping[str, str], store: Store, exclude: Sequence[str] = ()) -> list[Stat]:
    stats: list[Stat] = []
    for path in sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p) and _kept(p, exclude)):
        before = store.blobs[a[path]] if path in a else b""
        after = store.blobs[b[path]] if path in b else b""
        if b"\0" in before + after:
            stats.append(Stat(path, 0, 0))
            continue
        ops = difflib.SequenceMatcher(None, _text_lines(before), _text_lines(after), autojunk=False).get_opcodes()
        stats.append(
            Stat(
                path,
                sum(j2 - j1 for tag, _, _, j1, j2 in ops if tag != "equal"),
                sum(i2 - i1 for tag, i1, i2, _, _ in ops if tag != "equal"),
            )
        )
    return stats


def grep_files(wt: CheckoutState, term: str) -> list[str]:
    """Tracked, non-binary files holding ``term`` as a whole word."""
    word = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])")
    found: list[str] = []
    for path in sorted(wt.index):
        data = wt.files.get(path)
        if data is not None and b"\0" not in data and word.search(data.decode("utf-8", "replace")):
            found.append(path)
    return found
