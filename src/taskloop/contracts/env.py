"""The process environment, owned here: the one module of the package (with the edge modules named in tests/rules/test_env_edge.py)
that touches os.environ. Reads go through `ambient`/`snapshot`, the engine's own handovers through `export`/`take`/`handover`."""
import os
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field

from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.ids import BeadId, parse_bead_id


@dataclass(frozen=True)
class Env:
    """A frozen copy of an environment: what code below the edge takes as a parameter instead of reading the process."""

    vars: Mapping[str, str] = field(default_factory=dict)

    def get(self, name: str, default: str = "") -> str:
        return self.vars.get(name, default)

    def __contains__(self, name: object) -> bool:
        return str(name) in self.vars


def snapshot() -> Env:
    return Env(dict(os.environ))


def ambient(name: str, default: str = "") -> str:
    """One variable of the process environment ('' or `default` when unset or empty)."""
    return os.environ.get(name) or default


def ambient_bead(name: str) -> BeadId | None:
    """A bead id held in the process environment, None when unset or empty; a value that is not a bead id is an error."""
    value = ambient(name)
    return parse_bead_id(value) if value else None


def ambient_set(name: str) -> bool:
    return name in os.environ


def export(var: EnvVar, value: str) -> None:
    os.environ[var.value] = value


def take(var: EnvVar) -> str:
    """Remove `var` and return what it held ('' when unset): a handover is read once."""
    return os.environ.pop(var.value, "")


@contextmanager
def handover(var: EnvVar, value: str) -> Generator[None]:
    """`var` is `value` inside the block and what it was before (or unset) after, on any error."""
    before = os.environ.get(var.value)
    os.environ[var.value] = value
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(var.value, None)
        else:
            os.environ[var.value] = before


@contextmanager
def patched(values: Mapping[str, str]) -> Generator[None]:
    """The process environment with `values` over it inside the block, restored whole after."""
    saved = dict(os.environ)
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)
