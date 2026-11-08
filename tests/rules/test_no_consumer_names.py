"""Consumer toolchain names stay only at explicit migration sites and quoted test fixtures (tl-w7lt.32)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROOTS = (ROOT / "src/taskloop", *(ROOT / "packages").glob("*/src"), ROOT / "skills/task-loop")
# Delegate was outside this task-loop-only scan before its source moved into packages/.
SKIP = {"_vendor", "tltestkit", "delegate"}
SUFFIXES = {".py", ".md", ".json"}
CONSUMERS = re.compile(r"unity|dotnet|nuget|msbuild|roslyn|prefab|asmdef|lifesim|\bfld\b", re.I)

UNTIL = " stays until PROFILEGEN A lands (tl-w7lt.32 A1/A2: profile fields)"
EXCEPTIONS = {
    "packages/asks/src/tlasks/testing.py": (22, "reason: quoted owner ask fixtures moved from tests/asks/samples.py; no consumer behavior"),
    "src/taskloop/app/doctor/setup.py": (5, "reason: project marks dict and unity-lease question" + UNTIL),
    "src/taskloop/app/doctor/setup_apply.py": (9, "reason: unity lease profile and host resource setup" + UNTIL),
    "packages/gate/src/tlgate/domain/produced.py": (4, "reason: dotnet build output matcher and helper" + UNTIL),
    "packages/gate/src/tlgate/domain/diag/matchers.py": (2, "reason: Roslyn/MSBuild diagnostic regex and format id" + UNTIL),
    "packages/kernel/src/tlkernel/config.py": (1, "reason: TEST_PATTERN names the UnityTest attribute" + UNTIL),
    "packages/kernel/src/tlkernel/reviewmatchers.py": (1, "reason: asmdef|unity|prefab review suffix matcher" + UNTIL),
    "packages/kernel/src/tlkernel/checkmatchers.py": (1, "reason: unity-slot wait parser docstring" + UNTIL),
    "packages/pipeline/src/tlpipeline/waits.py": (1, "reason: unity-slot output parsing and wait accounting docstring" + UNTIL),
}


def hits() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for top in ROOTS:
        for path in sorted(top.rglob("*")):
            if not path.is_file() or path.suffix not in SUFFIXES or SKIP.intersection(path.relative_to(ROOT).parts):
                continue
            name = path.relative_to(ROOT).as_posix()
            for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if CONSUMERS.search(line):
                    found.setdefault(name, []).append(f"{name}:{n}: {line.strip()[:100]}")
    return found


def test_no_file_names_a_consumer_outside_migration_sites():
    found = hits()
    failures = []
    for name in sorted(found.keys() | EXCEPTIONS.keys()):
        lines = found.get(name, [])
        expected = EXCEPTIONS.get(name, (0, ""))[0]
        if len(lines) != expected:
            failures.append(f"{name}:1: expected {expected} hit lines, found {len(lines)}\n" + "\n".join(lines))
    assert not failures, "\n".join(failures)


def test_every_exception_has_a_reason():
    assert all(reason.strip() for _, reason in EXCEPTIONS.values())
