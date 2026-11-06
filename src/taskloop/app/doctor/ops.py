"""`tl doctor` ops checks: release clones that lag their origin, and capabilities the engine's requests rely on."""
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from taskloop.contracts.ports import Git

REQUIRED_CAPABILITIES: Final = ("instructions_ref",)  # a reviewer request carries the base commit (--instructions-ref)


def clone_line(name: str, behind: int) -> str:
    """The warning for a release clone `behind` commits behind its origin/main; '' when it is current."""
    if behind <= 0:
        return ""
    return f"release clone {name} is {behind} commit{'s' if behind != 1 else ''} behind its origin/main (as of its last fetch)"


def clone_warnings(config: Path, git: Git) -> list[str]:
    """One warning per <config>/release/<hash> clone that lags; the doctor never fetches, so this is the state of the last fetch."""
    root = config / "release"
    if not root.is_dir():
        return []
    out = []
    for clone in sorted(p for p in root.iterdir() if p.is_dir()):
        line = clone_line(clone.name, len(git.log(str(clone), ["origin/main"], ["HEAD"])))
        if line:
            out.append(line)
    return out


def capability_gap(contract: Mapping[str, object]) -> str:
    """The warning for a delegate contract that lacks a capability in REQUIRED_CAPABILITIES; '' when it has them all."""
    have = contract.get("capabilities")
    missing = [c for c in REQUIRED_CAPABILITIES if not isinstance(have, list) or c not in have]
    return f"delegate lacks capabilities the engine relies on: {', '.join(missing)}" if missing else ""
