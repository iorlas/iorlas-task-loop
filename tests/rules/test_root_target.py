"""Pin Denis's 2026-11-08 root targets on the real tree.

The per-file change ratchet (ratchet_change.py) already fails every rise against
its merge base. These absolute caps catch slow drift through allowed
`Ratchet-allow: root` rises. Hooks are the documented stdlib-only exception:
PreToolUse/pre-push branches are counted apart. SLOC is reported, not a reduction
target; engine attributes are reported without a cap.
"""

from rules import root_ratchet

BRANCH_CAP = 90
LONG_FUNCTION_CAP = 8
SLOC_BOUND = 3458
HOOK = "src/taskloop/hook/"


def test_root_targets():
    rows = root_ratchet.root_counts(root_ratchet.ROOT)
    attributes = root_ratchet.engine_attributes()
    context = f"engine attributes: {attributes}; run uv run python dev/root_report.py"
    branches = sum(counts["branch"] for rel, counts in rows if not rel.startswith(HOOK))
    long_functions = sum(counts["long_function"] for _, counts in rows)
    sloc = sum(counts["sloc"] for _, counts in rows)
    assert branches <= BRANCH_CAP, f"root branches outside hook/: {branches}, cap <= {BRANCH_CAP}; {context}"
    assert long_functions <= LONG_FUNCTION_CAP, f"root long functions: {long_functions}, cap <= {LONG_FUNCTION_CAP}; {context}"
    assert sloc < SLOC_BOUND, f"root SLOC: {sloc}, cap < {SLOC_BOUND}; {context}"


def test_hook_exemption_names_real_roots():
    paths = sorted((root_ratchet.ROOT / HOOK).rglob("*.py"))
    attributes = root_ratchet.engine_attributes()
    context = f"engine attributes: {attributes}; run uv run python dev/root_report.py"
    assert paths, f"hook files: {len(paths)}, required > 0; {context}"
    non_roots = [path.relative_to(root_ratchet.ROOT).as_posix() for path in paths
                 if not root_ratchet.is_root(path.relative_to(root_ratchet.ROOT).as_posix())]
    assert not non_roots, f"non-root hook files: {len(non_roots)}, cap 0: {non_roots}; {context}"
