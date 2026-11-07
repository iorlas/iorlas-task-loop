"""Why a gate step is not green, in words: the first RunKey field where the expected key and the newest stored receipt of that check on
the judged tree and base part. Display only: it never authorizes anything (RunMemo.result does)."""
from tlkernel import wire
from tlkernel.checks import Check
from tlkernel.runkey import Digest, RunKey

from tlgate.cache import RunMemo

PLURAL = frozenset({"dependencies", "inputs"})
INPUTS_HINT = "; gitignored files under its inputs count: judge in the worktree that ran it"


def first_difference(expected: RunKey, found: RunKey) -> str:
    """'<field> differs (expected abcd.. found ef01..)' for the first field in key order that differs; '' when the keys are equal."""
    want, have = wire.dump(expected), wire.dump(found)
    for name, value in want.items():
        if have.get(name) != value:
            verb = "differ" if name in PLURAL else "differs"
            return f"{name} {verb} (expected {short(value)} found {short(have.get(name))}){INPUTS_HINT if name == 'inputs' else ''}"
    return ""


def short(value: object) -> str:
    return str(value)[:12] if value else "none"


def unkeyed(memo: RunMemo, c: Check) -> str:
    """Why this check has no key here at all."""
    if not c.cache:
        return "it is not cacheable (cache: false): no receipt can count"
    if c.reads and memo.dependencies_of(c) is None:
        return f"a producer it reads ({', '.join(c.reads)}) has no matching receipt"
    return "its inputs select nothing in this tree"


def why_red(memo: RunMemo, c: Check, plan: Digest) -> str:
    """The first differing field against the newest receipt of the check on this tree and base, or why there is nothing to compare."""
    found = memo.latest(c)
    if found is None:
        return f"no green run of tree {memo.keys.tree[:12]} under `{c.cmd}`"
    expected = memo.planned_key(c, plan, found.key.plan_output) if found.result.planned else memo.key(c)
    if expected is None:
        return unkeyed(memo, c)
    return first_difference(expected, found.key) or "its receipt matches the key but is not a pass"
