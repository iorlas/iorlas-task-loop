"""`tl doctor` ops checks: release clones that lag their origin, and capabilities the engine's requests rely on."""
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from tlkernel.gitport import Git
from tlkernel.trace import RunTrace

SHARE_OF_BEADS: Final = 20  # the doctor looks at this many of the latest beads for the second family's routed share
WORKER_ROLE: Final = "worker"
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


def second_share(runs: Sequence[RunTrace], second: str, last: int = SHARE_OF_BEADS) -> tuple[int, int]:
    """(beads whose worker ran on `second`, beads counted): the latest `last` beads by their latest run, a bead once however many runs
    and calls it had."""
    latest: dict[str, float] = {}
    on_second: set[str] = set()
    for r in runs:
        latest[r.bead] = max(latest.get(r.bead, r.ended), r.ended)
        if any(c.role == WORKER_ROLE and c.family.lower() == second.lower() for c in r.sessions):
            on_second.add(r.bead)
    beads = sorted(latest, key=lambda b: latest[b])[-last:]
    return sum(1 for b in beads if b in on_second), len(beads)


def second_share_line(second: str, routed: int, of: int) -> str:
    return f"second_writer_family {second} routed: " + (f"{routed} of the last {of} beads" if of else "no runs yet")
