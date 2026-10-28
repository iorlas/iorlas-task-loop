"""A git that answers from a table: the land code's logic tests run without a repository or a process.

`FakeGit` is the `git` and `sh` the land classes read off their host. A reply is keyed by the argv it answers: leading words joined by
`__`, `_` standing for `-` (`rev_parse`, `diff__name_only`);
the longest key that starts the call wins; a call nothing answers fails the test by name, so a new git call cannot slip in unseen.
Real git stays in the integration tests (tests/test_stages_land.py and the push-race cells), where the behaviour of git itself is the point.
"""
from typing import Any


class FakeGit:
    def __init__(self, **replies: Any) -> None:
        self.replies: dict[tuple[str, ...], Any] = {tuple(w.replace("_", "-") for w in k.split("__")): v for k, v in replies.items()}
        self.calls: list[tuple[str, ...]] = []

    def answer(self, argv: tuple[str, ...]) -> Any:
        self.calls.append(argv)
        for n in range(len(argv), 0, -1):
            if argv[:n] in self.replies:
                reply = self.replies[argv[:n]]
                return reply.pop(0) if isinstance(reply, list) else reply
        raise AssertionError(f"git {' '.join(argv)}: no reply scripted")

    def git(self, *argv: str) -> str:
        return str(self.answer(argv))

    def sh(self, argv: list[str], **_: Any) -> tuple[int, str]:
        assert argv[0] == "git", argv
        out = self.answer(tuple(argv[1:]))
        return out if isinstance(out, tuple) else (0, str(out))

    def ran(self, *prefix: str) -> bool:
        return any(c[: len(prefix)] == prefix for c in self.calls)
