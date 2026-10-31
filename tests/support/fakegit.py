"""A Git port that answers from a table: the land code's logic tests run without a repository or a process.

`ScriptedGit` is the Git a land class reads off its host, over the real adapter with its one door shut: a git method nobody scripted
fails the test by name, so a new git call cannot slip in unseen. `FakeGit(**replies)` scripts it: a reply is keyed by the method and
leading arguments, joined by `__` (`rev_parse__origin/main`, `unmerged`); the longest key that starts the call wins; a list is a
sequence, one answer per call. `sh` answers the land command the engine's shell runs. What git itself does stays in the gitsim cells and
the real/ tests, where it is the point.
"""

from collections.abc import Sequence
from typing import Any

from taskloop.adapters.git import RealGit
from taskloop.contracts.env import Env
from taskloop.contracts.gitfacts import GitOutcome, LogRow
from taskloop.contracts.slots import SlotGitError


class ScriptedGit(RealGit):
    def __init__(self) -> None:
        super().__init__(Env())
        self.calls: list[tuple[str, ...]] = []

    def _run(self, d: str, *args: str, stdin: str | None = None, timeout: float | None = None, extra: dict[str, str] | None = None) -> Any:
        raise AssertionError(f"a git process ran: git {' '.join(args)}")

    def seen(self, *call: str) -> None:
        self.calls.append(call)

    def ran(self, *prefix: str) -> bool:
        return any(c[: len(prefix)] == prefix for c in self.calls)


class FakeGit(ScriptedGit):
    def __init__(self, **replies: Any) -> None:
        super().__init__()
        self.replies: dict[tuple[str, ...], Any] = {tuple(k.split("__")): v for k, v in replies.items()}

    def answer(self, name: str, *key: str, default: Any = None) -> Any:
        self.seen(name, *key)
        for n in range(len(key), -1, -1):
            if (name, *key[:n]) in self.replies:
                reply = self.replies[(name, *key[:n])]
                return reply.pop(0) if isinstance(reply, list) else reply
        if default is None:
            raise AssertionError(f"git {name} {' '.join(key)}: no reply scripted")
        return default

    def sh(self, argv: Sequence[str], **_: Any) -> tuple[int, str]:
        """The land command (`git push ...`) as the engine's shell runs it; keyed by its first word after git."""
        assert argv[0] == "git", argv
        out = self.answer(argv[1], *argv[2:])
        return out if isinstance(out, tuple) else (0, str(out))

    def common_dir(self, d: str) -> str:
        return str(self.answer("common_dir", default=""))

    # -- the reads the land asks ----------------------------------------------------------------------------------------------
    def rev_parse(self, d: str, rev: str) -> str:
        return str(self.answer("rev_parse", rev))

    def merge_base(self, d: str, a: str, b: str) -> str:
        return str(self.answer("merge_base", a, b))

    def branch(self, d: str) -> str:
        return str(self.answer("branch"))

    def dirty(self, d: str) -> bool:
        return bool(self.answer("dirty"))

    def staged(self, d: str) -> bool:
        return bool(self.answer("staged"))

    def count(self, d: str, include: list[str], exclude: list[str] | None = None) -> int:
        return int(self.answer("count", *include))

    def is_ancestor(self, d: str, a: str, b: str) -> bool:
        return bool(self.answer("is_ancestor"))

    def unmerged(self, d: str) -> list[str]:
        out = self.answer("unmerged")
        return list(out) if isinstance(out, (list, tuple)) else str(out).split()

    def log(self, d: str, include: list[str], exclude: list[str] | None = None, limit: int = 0, grep: str = "") -> list[LogRow]:
        row = self.answer("log")  # (oid, subject), or "" for no commit
        return [LogRow(oid=row[0], time=0, subject=row[1])] if row else []

    # -- the writes: recorded, and scripted when the test wants git to say no --------------------------------------------------
    def rebase(self, d: str, onto: str, update_refs: bool = True) -> GitOutcome:
        rc, text = self.answer("rebase", onto)
        return GitOutcome(ok=rc == 0, output=text)

    def rebase_abort(self, d: str) -> None:
        self.answer("rebase_abort", default="")

    def reset(self, d: str, rev: str, mode: Any = "mixed") -> None:
        self.answer("reset", mode, default="")

    def fail(self, name: str, why: str) -> SlotGitError:
        self.seen(name)
        return SlotGitError(why)
