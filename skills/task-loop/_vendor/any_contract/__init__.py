"""The neutral half of a wire contract between two programs.

Two repos (a caller and the tool it drives) each hold a codec for the same JSON (msgspec in one, dataclasses in the
other). The codec stays theirs. What is the same in both is this:

- ``check_contract``: does the remote speak my contract number (and the capabilities I need)? If not, a
  :class:`Violation` whose text is ready to become a synthesized ``contract_violation`` result, never an exception.
- ``diff_schema``: a local mirror's JSON schema against the remote's published one, field by field and enum by enum,
  so a drift is a named path, not a surprise at runtime; ``undeclared`` compares it with the drift you accepted.

Standard library only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = ["Violation", "check_contract", "diff_schema", "undeclared"]

_SHOWN = 300


@dataclass(frozen=True)
class Violation:
    """A remote that does not speak this contract; :attr:`text` says why, with a bounded excerpt of what it sent."""

    text: str


def check_contract(
    local_number: int,
    remote: object,
    *,
    key: str = "contract",
    capabilities: Iterable[str] = (),
    capabilities_key: str = "capabilities",
) -> Violation | None:
    """``None`` when ``remote`` (a parsed object or its JSON text) carries ``key == local_number`` and every capability.

    Anything else is a :class:`Violation`: not JSON, not an object, another number, or a missing capability (a list or
    a string of names under ``capabilities_key``).
    """
    doc: Any = remote
    if isinstance(remote, str | bytes):
        try:
            doc = json.loads(remote)
        except ValueError:
            return Violation(f"not JSON, so not contract {local_number}: {_excerpt(remote)}")
    if not isinstance(doc, dict):
        return Violation(f"not an object, so not contract {local_number}: {_excerpt(doc)}")
    if doc.get(key) != local_number:
        return Violation(f"an answer that is not contract {local_number} ({key}={doc.get(key)!r}): {_excerpt(doc)}")
    have = doc.get(capabilities_key, [])
    names = {have} if isinstance(have, str) else set(have) if isinstance(have, list) else set()
    missing = sorted(set(capabilities) - names)
    if missing:
        return Violation(f"contract {local_number} without capability {', '.join(missing)}")
    return None


def _excerpt(value: object) -> str:
    return f"{value!r:.{_SHOWN}}"


def _node(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def diff_schema(want: Mapping[str, Any], have: Mapping[str, Any], path: str = "") -> dict[str, tuple[tuple[Any, ...], tuple[Any, ...]]]:
    """Every difference between two JSON schemas, keyed ``<path>.fields`` or ``<path>.enum``.

    Each value is ``(only in want, only in have)``, sorted. Fields are ``properties`` plus ``required``; the walk goes
    into properties, ``items`` (path ``[]``), ``additionalProperties`` (``{}``) and ``anyOf``/``oneOf`` (``[i]``).
    """
    out: dict[str, tuple[tuple[Any, ...], tuple[Any, ...]]] = {}
    wanted = set(_node(want.get("properties"))) | set(want.get("required", []))
    actual = set(_node(have.get("properties"))) | set(have.get("required", []))
    for facet, left, right in (
        ("fields", wanted, actual),
        ("enum", set(want.get("enum", [])), set(have.get("enum", []))),
    ):
        if left != right:
            out[f"{path}.{facet}"] = (tuple(sorted(left - right, key=repr)), tuple(sorted(right - left, key=repr)))
    for name in wanted | actual:
        out.update(
            diff_schema(
                _node(_node(want.get("properties")).get(name)),
                _node(_node(have.get("properties")).get(name)),
                f"{path}.{name}",
            )
        )
    for key, suffix in (("items", "[]"), ("additionalProperties", "{}")):
        left, right = want.get(key), have.get(key)
        if isinstance(left, dict) or isinstance(right, dict):
            out.update(diff_schema(_node(left), _node(right), path + suffix))
    for key in ("anyOf", "oneOf"):
        left_list, right_list = want.get(key, []), have.get(key, [])
        for i in range(max(len(left_list), len(right_list))):
            out.update(
                diff_schema(
                    _node(left_list[i] if i < len(left_list) else None),
                    _node(right_list[i] if i < len(right_list) else None),
                    f"{path}.{key}[{i}]",
                )
            )
    return out


def undeclared(
    found: Mapping[str, tuple[tuple[Any, ...], tuple[Any, ...]]],
    known: Mapping[str, tuple[tuple[Any, ...], tuple[Any, ...], str]],
) -> tuple[list[str], list[str]]:
    """``(new, resolved)``: differences nobody accepted, and accepted ones that are now gone or changed.

    ``known`` maps a path to ``(only in want, only in have, reason)``; an entry must match exactly, so a drift that
    shrinks or grows is reported as both, and a fixed one cannot stay listed.
    """
    new = sorted(p for p, v in found.items() if p not in known or known[p][:2] != v)
    resolved = sorted(p for p, v in known.items() if p not in found or found[p] != v[:2])
    return new, resolved
