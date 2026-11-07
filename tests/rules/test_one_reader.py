"""One reader per fact (tl-sqd3.30, RCA R-A): a fact (the repo profile, the delivery verdict) is read by a named set of modules. The set is
the whole list, not a floor: a new reader fails here until it is named with its reason, and a reader removed must leave the list, so
the list can only shrink toward the target (one reader). The repo key's single definition site is tests/rules/test_one_repo_key.py."""
import ast

from rules.gate_rules import ROOT, parsed, py_files

SCAN = ("src", "packages")

# fact -> (the call names that read it, the modules that may, each with why). Target for every fact: one module.
FACTS = {
    "profile": (
        {"raw_at", "profile_at", "raw_in", "load", "load_profile"},
        {"profile_at", "config", "slots_config"},
        {
            "packages/gate/src/tlgate/authorization.py": "the judged tree's profile for the gate (to fold into the one reader)",
            "packages/kernel/src/tlkernel/profile_at.py": "THE reader: opens a commit's, tree's or working tree's file",
            "packages/slots/src/tlslots/config.py": "slots/base section of the profile (to read through profile_at only)",
            "packages/slots/src/tlslots/profile_facts.py": "doctor facts about the slots section (to fold)",
            "src/taskloop/app/doctor/profiles.py": "doctor's red row for a bad profile (to fold)",
            "src/taskloop/app/land/stackgate.py": "the gate of the stack's base commit (to fold)",
        },
    ),
    "delivery verdict": (
        {"results"},
        {"authorization"},
        {
            "packages/gate/src/tlgate/authorization.py": "THE reader: a check result only counts under the executed key",
            "src/taskloop/app/land/push_judge.py": "the pre-push judge",
            "src/taskloop/app/land/stackgate.py": "the stack's gate",
            "src/taskloop/cli/green.py": "`tl green`, the owner's view of the same verdict",
        },
    ),
}

HOME = {"profile": {"packages/kernel/src/tlkernel/profile_at.py"}, "delivery verdict": {"packages/gate/src/tlgate/authorization.py"}}


def readers(tree: ast.Module, calls: set[str], owners: set[str]) -> bool:
    """True when the module calls `<owner>.<call>(...)` for one of the fact's owners and call names."""
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in calls
        and isinstance(n.func.value, ast.Name) and n.func.value.id in owners
        for n in ast.walk(tree)
    )


def test_each_fact_has_the_readers_it_names_and_no_other():
    found: dict[str, set[str]] = {fact: set() for fact in FACTS}
    for path in py_files(ROOT, scan=SCAN):
        rel = path.relative_to(ROOT).as_posix()
        if "/tests/" in rel:
            continue
        tree = parsed(path)[1]
        for fact, (calls, owners, _) in FACTS.items():
            if readers(tree, calls, owners):
                found[fact].add(rel)
            if rel in HOME[fact]:
                found[fact].add(rel)  # the home module defines the fact, so it is a reader by definition
    assert {fact: sorted(paths) for fact, paths in found.items()} == {fact: sorted(spec[2]) for fact, spec in FACTS.items()}


def test_the_scan_sees_a_reader():
    tree = ast.parse("x = profile_at.raw_in(repo)\n")
    assert readers(tree, FACTS["profile"][0], FACTS["profile"][1])
    assert not readers(ast.parse("x = other.raw_in(repo)\n"), FACTS["profile"][0], FACTS["profile"][1])
