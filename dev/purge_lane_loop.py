"""Purge factory-loop terminology only; prepare with --root DIR on a disposable copy.

Exact replacement counts accept either the original or completed form of each
edit. Preflight reports every rewrite and unsupported form before any write.
Remaining lane lines are an audited allowlist of account/check-track meanings;
drift in those lines requires review rather than a guessed semantic rewrite.
Dashboard cards, delegate, architecture, and historical audits are excluded.
"""
import argparse
import re
from collections import Counter
from pathlib import Path

# (file, old, new, expected old count, pre-existing new count).
REPLACEMENTS = (
    ('src/taskloop/app/loop/ports.py', 'idle_lanes', 'idle_loops', 1, 0,),
    ('src/taskloop/app/loop/stages.py', 'idle_lanes', 'idle_loops', 3, 0,),
    ('src/taskloop/app/loop/loop.py', 'idle_lanes', 'idle_loops', 1, 0,),
    ('packages/slots/src/tlslots/liveness.py', 'idle_lanes', 'idle_loops', 4, 0,),
    ('packages/slots/src/tlslots/watchdog.py', 'idle_lanes', 'idle_loops', 6, 0,),
    ('packages/slots/tests/test_liveness.py', 'idle_lanes', 'idle_loops', 4, 0,),
    ('packages/slots/src/tlslots/liveness.py', 'lane(s) are idle', 'loop(s) are idle', 1, 0,),
    ('packages/slots/src/tlslots/liveness.py', 'an idle lane', 'an idle loop', 1, 0,),
    ('packages/slots/tests/test_liveness.py', 'an_idle_lane', 'an_idle_loop', 1, 0,),
    ('README.md', "The first lane's PID", "The first loop's PID", 1, 0,),
    ('README.md', 'factory-lane-K.log', 'factory-loop-K.log', 1, 0,),
    ('docs/design/roadmap.md', 'lanes running in parallel', 'streams running in parallel', 1, 0,),
    ('docs/design/gate-host.md',
        '   factory lanes, not four (see the arithmetic below). **Do this second, as an overflow executor in front of the',
        '   factory loops, not four (see the arithmetic below). **Do this second, as an overflow executor in front of the', 1, 0,),
    ('docs/design/gate-host.md', (
        '| Mac run logs, load samples, Mac core count | **Not reachable.** Only the facts the owner gave: faults about 650 s'
        ', test about 500 s, design-tests about 400 s under load; Unity steps 3-5 min each, unity lease 1; load reached 281 '
        'with 4 factory lanes; GitHub/PyPI timeouts under load. |'
    ), (
        '| Mac run logs, load samples, Mac core count | **Not reachable.** Only the facts the owner gave: faults about 650 s'
        ', test about 500 s, design-tests about 400 s under load; Unity steps 3-5 min each, unity lease 1; load reached 281 '
        'with 4 factory loops; GitHub/PyPI timeouts under load. |'
    ), 1, 0,),
    ('docs/design/gate-host.md', (
        '| beads | No GATECLEAN bead exists (`bd list --all`, read-only). Related beads: `tl-3cl.3` CHECKIDENT (closed, rele'
        'ased 0.23.293), `tl-3cl.4` GATESELECT (open), `tl-4af` multi-machine dashboard (open), `tl-sqd3.24` delegate lock l'
        'oad under 4 lanes (open). |'
    ), (
        '| beads | No GATECLEAN bead exists (`bd list --all`, read-only). Related beads: `tl-3cl.3` CHECKIDENT (closed, rele'
        'ased 0.23.293), `tl-3cl.4` GATESELECT (open), `tl-4af` multi-machine dashboard (open), `tl-sqd3.24` delegate lock l'
        'oad under 4 loops (open). |'
    ), 1, 0,),
    ('docs/design/gate-host.md',
        "  (`src/taskloop/domain/checks/plan.py:25-30`, `contracts/checks.py:81`). lifesim's checks name none, so each factory lane",
        "  (`src/taskloop/domain/checks/plan.py:25-30`, `contracts/checks.py:81`). lifesim's checks name none, so each factory loop", 1,
        0,),
    ('docs/design/gate-host.md',
        '  runs its gate steps one after another (`app/checks/executor.py:77-88`). The parallelism comes from the 4 factory lanes',
        '  runs its gate steps one after another (`app/checks/executor.py:77-88`). The parallelism comes from the 4 factory loops', 1, 0,),
    ('docs/design/gate-host.md', '## 2. Part (a): capping .NET and the lanes', '## 2. Part (a): capping .NET and the loops', 1, 0,),
    ('docs/design/gate-host.md', (
        '| `-nodeReuse:false` / `MSBUILDNODEREUSE=0` | build | nodes exit after the build instead of idling. They use no CPU'
        ' while idle, only memory. With 4 lanes x N idle nodes that is GBs of RAM, not load | yes (memory) |'
    ), (
        '| `-nodeReuse:false` / `MSBUILDNODEREUSE=0` | build | nodes exit after the build instead of idling. They use no CPU'
        ' while idle, only memory. With 4 loops x N idle nodes that is GBs of RAM, not load | yes (memory) |'
    ), 1, 0,),
    ('docs/design/gate-host.md', (
        '| `UseSharedCompilation=false` | build | **raises** CPU: every csc starts and JITs again | **no**: keep the shared '
        'compiler server, one per user across all lanes |'
    ), (
        '| `UseSharedCompilation=false` | build | **raises** CPU: every csc starts and JITs again | **no**: keep the shared '
        'compiler server, one per user across all loops |'
    ), 1, 0,),
    ('docs/design/gate-host.md', (
        '| `dotnet test --max-parallel-test-modules 1` | justfile `test` | one test project at a time per lane | optional (e'
        'st. halves peak test threads) |'
    ), (
        '| `dotnet test --max-parallel-test-modules 1` | justfile `test` | one test project at a time per loop | optional (e'
        'st. halves peak test threads) |'
    ), 1, 0,),
    ('docs/design/gate-host.md', (
        '| design-tests workers | `run_tests_parallel.py:97` | `max_workers=min(4, cpu_count)` or an env override (lifesim c'
        'hange) | yes: est. 4N to 16 processes across 4 lanes |'
    ), (
        '| design-tests workers | `run_tests_parallel.py:97` | `max_workers=min(4, cpu_count)` or an env override (lifesim c'
        'hange) | yes: est. 4N to 16 processes across 4 loops |'
    ), 1, 0,),
    ('docs/design/gate-host.md', (
        '| **A. Global compute lease** `dotnet` | `engine.resources.dotnet.limit = 2`; `needs: ["dotnet"]` on build, test, f'
        'aults, allocation, content (the same mechanism as unity, `resources.py:72-107`) | **none** in the engine. Profile e'
        'dit, plus `"dotnet"` added to the Mac\'s `host.json` if it lists resources, or every dotnet check is deferred (`affi'
        'nity.py:22-24`, `executor.py:109`) | at most 2 lanes in a .NET step at once |'
    ), (
        '| **A. Global compute lease** `dotnet` | `engine.resources.dotnet.limit = 2`; `needs: ["dotnet"]` on build, test, f'
        'aults, allocation, content (the same mechanism as unity, `resources.py:72-107`) | **none** in the engine. Profile e'
        'dit, plus `"dotnet"` added to the Mac\'s `host.json` if it lists resources, or every dotnet check is deferred (`affi'
        'nity.py:22-24`, `executor.py:109`) | at most 2 loops in a .NET step at once |'
    ), 1, 0,),
    ('docs/design/gate-host.md', (
        '| **D. Load-aware lane start** | the loop waits before `queue()` while `os.getloadavg()[0] > 2 x cores` (`app/loop/'
        'loop.py:201-218`) | small engine change; shows as a loop wait | stops new beads being admitted while the machine is'
        ' overloaded; running gates are not touched |'
    ), (
        '| **D. Load-aware loop start** | the loop waits before `queue()` while `os.getloadavg()[0] > 2 x cores` (`app/loop/'
        'loop.py:201-218`) | small engine change; shows as a loop wait | stops new beads being admitted while the machine is'
        ' overloaded; running gates are not touched |'
    ), 1, 0,),
    ('docs/design/gate-host.md',
        'Inputs: Mac logical cores N (unknown; **12** is used as the example, an M-series Pro); 4 factory lanes; per-lane thread',
        'Inputs: Mac logical cores N (unknown; **12** is used as the example, an M-series Pro); 4 factory loops; per-loop thread', 1, 0,),
    ('docs/design/gate-host.md',
        '- **Today:** 4 lanes x (between N and 4N) = 4N to 16N = 48 to 192 runnable threads for N=12, plus the Unity editor,',
        '- **Today:** 4 loops x (between N and 4N) = 4N to 16N = 48 to 192 runnable threads for N=12, plus the Unity editor,', 1, 0,),
    ('docs/design/gate-host.md',
        "  design-tests' N processes per lane (up to 48), the Codex and delegate processes, and git/uv. The reported 281 ≈ 23 per core",
        "  design-tests' N processes per loop (up to 48), the Codex and delegate processes, and git/uv. The reported 281 ≈ 23 per core",
        1, 0,),
    ('docs/design/gate-host.md',
        '- **With A + B (dotnet limit 2, K=4, CsCheck 1):** 2 lanes x (3 modules x 4 + 1) ≈ 26, or 2 x 4 = 8 with',
        '- **With A + B (dotnet limit 2, K=4, CsCheck 1):** 2 loops x (3 modules x 4 + 1) ≈ 26, or 2 x 4 = 8 with', 1, 0,),
    ('docs/design/gate-host.md',
        '  `--max-parallel-test-modules 1`. Add design-tests capped at 4 per lane (≤ 16), Unity ≈ 4-8 (est.), and other processes',
        '  `--max-parallel-test-modules 1`. Add design-tests capped at 4 per loop (≤ 16), Unity ≈ 4-8 (est.), and other processes', 1, 0,),
    ('docs/design/gate-host.md',
        '- **Gate wall time:** the CPU work is the same core-seconds either way. Today the 4 lanes share N cores, about N/4 each. With',
        '- **Gate wall time:** the CPU work is the same core-seconds either way. Today the 4 loops share N cores, about N/4 each. With',
        1, 0,),
    ('docs/design/gate-host.md',
        '  the lease, 2 lanes get about N/2 each, and the other 2 wait on the lease (an `RESOURCE` wait in the wait log, outside',
        '  the lease, 2 loops get about N/2 each, and the other 2 wait on the lease (an `RESOURCE` wait in the wait log, outside', 1, 0,),
    ('docs/design/gate-host.md', (
        '  the budget) while their writers keep working (writers are remote AI calls and use little CPU). Per-lane gate thro'
        'ughput is **about'
    ), (
        '  the budget) while their writers keep working (writers are remote AI calls and use little CPU). Per-loop gate thro'
        'ughput is **about'
    ), 1, 0,),
    ('docs/design/gate-host.md',
        '**Devbox throughput.** Under load each Mac lane gets about N/4 = 3 cores, so the heavy chain is ≈ (650+500) x 3 ≈ **3450',
        '**Devbox throughput.** Under load each Mac loop gets about N/4 = 3 cores, so the heavy chain is ≈ (650+500) x 3 ≈ **3450', 1, 0,),
    ('docs/design/gate-host.md',
        '| (a) caps only | ≈ 30-55 | ≈ the same per gate (est. ±15 %); 2 of 4 lanes queue on the dotnet lease | timeouts largely gone |',
        '| (a) caps only | ≈ 30-55 | ≈ the same per gate (est. ±15 %); 2 of 4 loops queue on the dotnet lease | timeouts largely gone |',
        1, 0,),
    ('docs/design/gate-host.md', (
        '| (b) with 4 lanes all gating | | devbox busy ≈ 13 min per gate; at one gate per lane every ≈ 45 min (unknown caden'
        "ce), demand = 4 x 13 / 45 ≈ **1.2 > 1** | about 2 lanes' worth at most; the rest fall back to the local lease |"
    ), (
        '| (b) with 4 loops all gating | | devbox busy ≈ 13 min per gate; at one gate per loop every ≈ 45 min (unknown caden'
        "ce), demand = 4 x 13 / 45 ≈ **1.2 > 1** | about 2 loops' worth at most; the rest fall back to the local lease |"
    ), 1, 0,),
    ('docs/design/gate-host.md', (
        "The cadence (gates per lane per hour) is the input that decides how many lanes one devbox serves. It is in the Mac'"
        's `runs/*/checks`'
    ), (
        "The cadence (gates per loop per hour) is the input that decides how many loops one devbox serves. It is in the Mac'"
        's `runs/*/checks`'
    ), 1, 0,),
    ('docs/design/gate-host.md', (
        '| 3 | **devbox as an overflow gate host** for build, test, allocation, faults (section 3) | L (identity, transport,'
        ' import, lane, fallback) | to ≈ 15-30 | \u22129-15 min per gate, for about 2 lanes | Linux portability of the suites unk'
        'nown; a new trust edge |'
    ), (
        '| 3 | **devbox as an overflow gate host** for build, test, allocation, faults (section 3) | L (identity, transport,'
        ' import, lane, fallback) | to ≈ 15-30 | \u22129-15 min per gate, for about 2 loops | Linux portability of the suites unk'
        'nown; a new trust edge |'
    ), 1, 0,),
    ('docs/design/gate-host.md', (
        '| 4 | load-aware lane start (`loop.py:201-218`) | S | caps admits only | none | it hides symptoms; useful as a guar'
        'd rail after 1 |'
    ), (
        '| 4 | load-aware loop start (`loop.py:201-218`) | S | caps admits only | none | it hides symptoms; useful as a guar'
        'd rail after 1 |'
    ), 1, 0,),
    ('docs/design/gate-host.md', (
        '| 5 | whole lifesim factory lanes on the devbox, using the existing bead affinity (`engine.py:272-279`) | M | some '
        '| - | `unity-analyzers`/`unity-tests` have `when: src/**, config/**, content/**` (lifesim `.task-loop.json`), so ne'
        'arly every sim bead needs unity and is moved back to the Mac. Only docs/design/tools beads benefit |'
    ), (
        '| 5 | whole lifesim factory loops on the devbox, using the existing bead affinity (`engine.py:272-279`) | M | some '
        '| - | `unity-analyzers`/`unity-tests` have `when: src/**, config/**, content/**` (lifesim `.task-loop.json`), so ne'
        'arly every sim bead needs unity and is moved back to the Mac. Only docs/design/tools beads benefit |'
    ), 1, 0,),
    ('docs/design/gate-host.md',
        '| 6 | `taskpolicy -b` for lanes | XS | load unchanged | heavy steps several times slower on E-cores (unverified) | no |',
        '| 6 | `taskpolicy -b` for loops | XS | load unchanged | heavy steps several times slower on E-cores (unverified) | no |', 1, 0,),
    ('docs/design/gate-host.md', (
        'gate cadence per lane. These two tables replace every **(est.)** in 2.3 and 3.6, and they decide whether slices 2-4'
        ' are worth building.'
    ), (
        'gate cadence per loop. These two tables replace every **(est.)** in 2.3 and 3.6, and they decide whether slices 2-4'
        ' are worth building.'
    ), 1, 0,),
    ('docs/design/gate-host.md', (
        '   `dotnet` (and `unity`). *Acceptance:* with 4 factory lanes gating, `sysctl vm.loadavg` sampled every 60 s over 2'
        ' h stays ≤ 60;'
    ), (
        '   `dotnet` (and `unity`). *Acceptance:* with 4 factory loops gating, `sysctl vm.loadavg` sampled every 60 s over 2'
        ' h stays ≤ 60;'
    ), 1, 0,),
    ('docs/design/gate-host.md', '   gate cadence per lane; a decision line: go or no-go for GATEHOST-*.',
        '   gate cadence per loop; a decision line: go or no-go for GATEHOST-*.', 1, 0,),
)

# Exact remaining lines, including account identifiers such as no_lane.
PRESERVED = (
    ('src/taskloop/app/loop/stages.py',
        'def chores[Config, Store](lanes: Callable[[], object], config: Callable[[], Config], sweep: Callable[[Config], object],', 1,),
    ('src/taskloop/app/loop/stages.py', '    lanes()', 1,),
    ('src/taskloop/app/loop/loop.py', '            self.wait = LoopWait(reason="no_lane", wake="retry due", probe_at=wake)', 1,),
    ('README.md', 'The engine, loop, run processes and worker lanes cannot use this flag; no environment variable grants approval.', 1,),
    ('README.md', 'Low disk, low available RAM and unavailable lanes keep loops alive as waits with explicit probe times and wake', 1,),
    ('README.md', (
        'conditions. Disk and RAM wake when their configured thresholds (`loop.min_free_gb`, `loop.min_ram_mb`) are met; lan'
        'es wake when usable or their retry is due. Stops and `--until` still work.'
    ), 1,),
    ('README.md',
        'on a normal loop pass; there is no timed set-aside. Resource and lane waits poll their wake conditions at the pass interval.', 1,),
    ('README.md', "- **Lanes:** each delegate lane's usage and state.", 1,),
    ('README.md',
        "                                 engine with a scripted lane, on this install's code), dash.py (tl dash), dash_ports.py", 1,),
    ('docs/design/roadmap.md', '| Goal | Beads | Lane |', 1,),
    ('docs/design/roadmap.md',
        '- tl-wnup.4 (255 temp-dir sites to the workdir fixture): wide test edit, run when no other lane has open test PRs.', 1,),
    ('docs/design/gate-host.md',
        '- **One check lane per gate in lifesim.** Execution splits into lanes only when the profile names a `lane`', 1,),
    ('docs/design/gate-host.md', '  and a cancelled lane stops waiting. This is how the unity lease works.', 1,),
    ('docs/design/gate-host.md',
        '| `allocation` | `... --filter-trait Lane=plain -- --parallel none` (justfile:222-223, gate_plan.py:855) | already serial |', 1,),
    ('docs/design/gate-host.md', '  meanwhile the Unity lane runs locally (unity lease)', 1,),
    ('docs/design/gate-host.md',
        '- The eligible checks become their own check lane (`lane: "remote"`, `contracts/checks.py:81`), so `Lanes` runs', 1,),
    ('docs/design/gate-host.md', (
        '  them alongside the local Unity lane, and the first red on either side cancels the other (`app/checks/lanes.py`, m'
        'odule docstring).'
    ), 1,),
    ('docs/design/gate-host.md', (
        '  than `lane_wait_min` (`contracts/config.py:223`), the lane runs locally under the `dotnet` lease from part (a). T'
        'his keeps the'
    ), 1,),
    ('docs/design/gate-host.md',
        '| devbox down / ssh times out | the lane falls back to local (dotnet lease); a wait event; no verdict lost |', 1,),
    ('docs/design/gate-host.md', (
        '| NuGet restore from the devbox network fails | `prepare` red is an infrastructure fault (`FAULT_INFRA`), the lane '
        'falls back to local |'
    ), 1,),
    ('docs/design/gate-host.md', (
        '| today | ≈ 281 (measured) | 60 + 400 + 500 + 650 + 9-20 min Unity ≈ **35-46 min** + unity lease wait | sequential '
        'in one check lane |'
    ), 1,),
    ('docs/design/gate-host.md', (
        '| (b) devbox + local Unity lane | ≈ 15-30 (Unity, light, writers) | max(12 min devbox + ≈ 1 min push and import, 9-'
        '20 min Unity) + light ≈ **21-27 min** | saves ≈ 9-15 min per gate *when the devbox is free* |'
    ), 1,),
    ('docs/design/gate-host.md', (
        '| 3 | **devbox as an overflow gate host** for build, test, allocation, faults (section 3) | L (identity, transport,'
        ' import, lane, fallback) | to ≈ 15-30 | \u22129-15 min per gate, for about 2 loops | Linux portability of the suites unk'
        'nown; a new trust edge |'
    ), 1,),
    ('docs/design/gate-host.md', (
        'imported). Slice 3, identity and authorization changes (3.3, items 1-4) behind `portable`. Slice 4, the remote lane'
        ', import and fallback'
    ), 1,),
    ('docs/design/gate-host.md', (
        '10. **GATEHOST-LANE: eligible checks run as a remote lane beside the Unity lane, falling back to local.** *Acceptan'
        'ce:* with the devbox'
    ), 1,),
)


def plan(root: Path) -> tuple[dict[Path, str], list[str], list[str]]:
    edits, reports, errors = {}, [], []
    names = dict.fromkeys(row[0] for row in REPLACEMENTS)
    for name in names:
        path = root / name
        if not path.is_file():
            errors.append(f'{name}: missing required file')
            continue
        original = path.read_text()
        text = original
        for filename, old, new, expected, existing in REPLACEMENTS:
            if filename != name:
                continue
            counts = (text.count(old), text.count(new))
            if counts == (expected, existing):
                reports.append(f'{name}: {expected} x {old!r} -> {new!r}')
                text = text.replace(old, new)
            elif counts != (0, existing + expected):
                errors.append(f'{name}: unsupported counts {counts} for {old!r}; expected '
                              f'{(expected, existing)} or {(0, existing + expected)}')
        allowed = Counter({line: count for filename, line, count in PRESERVED if filename == name})
        remaining = Counter(line for line in text.splitlines() if re.search('lane', line, re.IGNORECASE))
        for line in sorted(remaining.keys() | allowed.keys()):
            if remaining[line] != allowed[line]:
                errors.append(f'{name}: unsupported lane line ({remaining[line]}, expected {allowed[line]}): {line}')
        if text != original:
            edits[path] = text
    errors.extend(unlisted_identifiers(root, names))
    return edits, reports, errors


def unlisted_identifiers(root: Path, names: dict[str, None]) -> list[str]:
    errors = []
    for folder in ('src', 'packages', 'tests', 'dev', 'skills'):
        for path in sorted((root / folder).rglob('*')):
            relative = path.relative_to(root)
            if (not path.is_file() or relative.as_posix() in names or relative.parts[:2] == ('packages', 'delegate')
                    or path.name == Path(__file__).name or any(part.startswith('.') or part == '__pycache__' for part in relative.parts)):
                continue
            try:
                text = path.read_text()
            except UnicodeError:
                continue
            if 'idle_lanes' in text:
                errors.append(f'{relative}: unsupported idle_lanes occurrence outside the replacement table')
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root.resolve()
    edits, reports, errors = plan(root)
    for report in reports:
        print(f'rewrite: {report}')
    for error in errors:
        print(f'unsupported: {error}')
    print(f'preflight: {len(reports)} replacements in {len(edits)} files; {len(errors)} unsupported forms')
    if errors:
        raise SystemExit('No files written.')
    for path, text in edits.items():
        path.write_text(text)
    print(f'rewrote {len(edits)} files')


if __name__ == '__main__':
    main()
