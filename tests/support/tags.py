"""Test tags. `@contract`: one suite run against the real adapter and its fake (or golden output), so they cannot drift.
`@domain`: logic over fakes, no process and no files. `@slow`: a real process."""
from typing import Any


def _tag(name: str) -> Any:
    def mark(cls: Any) -> Any:
        cls.tags = frozenset(getattr(cls, "tags", frozenset()) | {name})
        return cls
    return mark


contract = _tag("contract")
domain = _tag("domain")
slow = _tag("slow")  # starts a real process and waits on it
