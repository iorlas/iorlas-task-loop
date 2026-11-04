"""engine.input_sets and engine.hatch: globs written once in the profile, named by `@name` wherever a check lists globs (`inputs`,
`exclude`, `when`, and `hatch`). A set holds plain globs (no `@` inside); a name nobody declared is refused at load; a set nobody
names is said by `tl doctor`. `hatch` lists the files whose change forces every check that is selected or keyed by globs: they join
its `inputs` and `when`."""
from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol

REF = "@"


class CheckSpec(Protocol):
    """What of a config.CheckSpec the sets read (config imports this module: it names no config type)."""

    @property
    def id(self) -> str: ...
    @property
    def inputs(self) -> str | Sequence[str]: ...
    @property
    def exclude(self) -> Sequence[str]: ...
    @property
    def when(self) -> Sequence[str]: ...


class EngineConfig(Protocol):
    @property
    def input_sets(self) -> Mapping[str, Sequence[str]]: ...
    @property
    def hatch(self) -> Sequence[str]: ...
    @property
    def checks(self) -> Sequence[CheckSpec]: ...


def listed(globs: str | Sequence[str]) -> list[str]:
    return [globs] if isinstance(globs, str) else list(globs)


def expand(eng: EngineConfig, globs: str | Sequence[str]) -> list[str]:
    """The plain globs of a list that may name sets (`@name`); a name that is not declared stays as written (load refused it already)."""
    out: list[str] = []
    for g in listed(globs):
        out += eng.input_sets.get(g[len(REF):], [g]) if g.startswith(REF) else [g]
    return out


def forced(eng: EngineConfig, globs: str | Sequence[str]) -> list[str]:
    """`inputs` or `when` of a check with the hatch files added; an empty list stays empty (no globs: the whole tree, or always)."""
    plain = expand(eng, globs)
    return [*plain, *expand(eng, eng.hatch)] if plain else plain


def _lists(k: CheckSpec) -> Iterable[Sequence[str]]:
    return listed(k.inputs), k.exclude, k.when


def used(eng: EngineConfig) -> set[str]:
    """The set names some check or the hatch refers to."""
    refs = [g for k in eng.checks for glist in _lists(k) for g in glist] + list(eng.hatch)
    return {g[len(REF):] for g in refs if g.startswith(REF)}


def unused(eng: EngineConfig) -> list[str]:
    """The declared sets nothing refers to."""
    return [n for n in eng.input_sets if n not in used(eng)]


def problem(eng: EngineConfig) -> str:
    """Why the sets do not fit ('' when they do): a set that names another, or a reference to a set nobody declared."""
    for name, globs in eng.input_sets.items():
        if any(g.startswith(REF) for g in globs):
            return f"engine.input_sets.{name} names another set; a set holds plain globs"
    for k in eng.checks:
        for glist in _lists(k):
            lost = [g for g in glist if g.startswith(REF) and g[len(REF):] not in eng.input_sets]
            if lost:
                return f"check {k.id} names {lost[0]}, which engine.input_sets does not declare"
    lost = [g for g in eng.hatch if g.startswith(REF) and g[len(REF):] not in eng.input_sets]
    return f"engine.hatch names {lost[0]}, which engine.input_sets does not declare" if lost else ""
