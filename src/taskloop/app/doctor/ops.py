"""`tl doctor` ops checks: release clones that lag their origin, and capabilities the engine's requests rely on."""
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tlkernel.gitport import Git

from taskloop.app.doctor.env_checks import Finding
from taskloop.app.doctor.setup_checks import Source

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


def product_lines(writer_exec: bool, reviewer_other_family: bool) -> list[str]:
    return [
        f"writer_exec: {'on' if writer_exec else 'off'} (delegate routing settings own the writer pin and exec grant)",
        f"reviewer_other_family: {'on' if reviewer_other_family else 'off'}",
    ]


@dataclass(frozen=True)
class DoctorFacts:
    """Ordered report inputs; effectful lookups stay deferred until their row is due."""
    repo: str
    contracts: Callable[[], Path]
    migrate_command: str
    profile: Callable[[], int]
    source: Callable[[], Source]
    slots: Callable[[], tuple[str, list[str]]]
    path_link: Callable[[], tuple[str, bool]]
    git_warnings: Callable[[Source], list[str]]
    layout_warnings: Callable[[Source], list[str]]
    bead_warnings: Callable[[], list[str]]
    clone_warnings: Callable[[], list[str]]
    capability_gap: Callable[[], str]
    lost_runs: Callable[[], list[str]]
    legacy: Callable[[], str]
    old_layout: Callable[[], list[str]]
    install_problems: Callable[[], list[str]]
    findings: Callable[[], list[Finding]]
    rails: Callable[[Source], list[str]]
    queue: Callable[[str], list[str]]


def report(facts: DoctorFacts) -> int:
    """Print setup rows in diagnostic order; only failures determine the exit code."""
    repo = facts.repo
    if facts.profile():  # a bad profile is a red row of its repo, not a traceback
        return 1
    source = facts.source()
    _, base, commit = source
    print(f"config: .task-loop.json from base {base} at commit {commit}" if commit else
          f"config: .task-loop.json from working tree {repo} (base {base} unresolved; no commit read)")
    slot_line, slot_warns = facts.slots()
    print(slot_line)
    link_line, foreign = facts.path_link()
    if not foreign:
        print(link_line)  # a foreign `tl` is a WARN below
    warns = facts.git_warnings(source) + facts.layout_warnings(source)
    warns += facts.bead_warnings() + slot_warns
    warns += [link_line] if foreign else []
    warns += facts.clone_warnings()
    warns += [gap] if (gap := facts.capability_gap()) else []
    warns += [f"run {r} is lost: its process is gone and it recorded no end" for r in facts.lost_runs()]
    print(f"contracts: {facts.contracts()}")
    for line in product_lines(source[0].engine.writer_exec, source[0].engine.reviewer_other_family):
        print(f"engine: {line}")
    for w in warns:
        print("WARN " + w)
    if legacy := facts.legacy():
        print(legacy)
    if old := facts.old_layout():
        print(f"WARN the config dir is in the old layout ({len(old)} places, first {old[0]}): "
              f"stop the loops, then run `{facts.migrate_command}`")
    fails = facts.install_problems()
    for p in fails:
        print("FAIL " + p)
    found = facts.findings()
    sys.stdout.write("".join(f.line() + "\n" for f in found))
    fails += [f.text for f in found if f.level == "FAIL"]
    fails += facts.rails(source)
    fails += facts.queue(source[1])
    if not warns and not found and not fails:
        print("ok: no setup problems found in " + repo)
    return 1 if fails else 0
