"""One reader per fact (tl-sqd3.30, RCA R-A): the repo profile and the delivery verdict each have one reader module (profile_at, authorization);
a second reader fails here. The stop reason is still open (tl-sqd3.30.2). The accessors authorization offers (`red`, `verdict`) are
answers, not the raw per-check mapping, so calling them is not reading the fact: do not widen the rule to them. The repo key's single
definition site is tests/rules/test_one_repo_key.py."""
import ast

from rules.gate_rules import ROOT, parsed, py_files

SCAN = ("src", "packages")

# fact -> (the call names that read it, the modules that may, each with why). Target for every fact: one module.
FACTS = {
    "profile": (
        {"raw_at", "raw_in", "object_of", "load", "load_profile", "loads"},
        {"profile_at", "config", "slots_config", "json"},
        {
            "packages/kernel/src/tlkernel/profile_at.py": "THE reader: opens and parses every repo profile",
        },
    ),
    "delivery verdict": (
        {"results"},
        {"authorization"},
        {
            "packages/gate/src/tlgate/authorization.py": "THE reader: a check result only counts under the executed key",
        },
    ),
}

HOME = {"profile": {"packages/kernel/src/tlkernel/profile_at.py"}, "delivery verdict": {"packages/gate/src/tlgate/authorization.py"}}


def readers(tree: ast.Module, calls: set[str], owners: set[str]) -> bool:
    """True when the module calls `<owner>.<call>(...)` for one of the fact's owners and call names."""
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in calls
        and isinstance(n.func.value, ast.Name) and n.func.value.id in owners
        and (n.func.value.id != "json" or n.func.attr == "loads")
        and (n.func.attr != "loads" or profile_text(n))
        for n in ast.walk(tree)
    )


def profile_text(call: ast.Call) -> bool:
    """Recognize explicit profile text names or a literal profile path, without tracing data flow."""
    return bool(call.args) and any(
        (isinstance(n, ast.Name) and n.id in {"profile_text", "profile"})
        or (isinstance(n, ast.Constant) and isinstance(n.value, str) and ".task-loop.json" in n.value)
        for n in ast.walk(call.args[0])
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


def test_profile_scan_distinguishes_typed_consumers_and_explicit_json_readers():
    calls, owners, _ = FACTS["profile"]
    for call in ('profile_at.object_of(text)', 'config.load(data)', 'slots_config.load_profile(data)',
                 'json.loads(profile_text)', 'json.loads((repo / ".task-loop.json").read_text())'):
        assert readers(ast.parse(call), calls, owners)
    for call in ('profile_at.profile_at(git, repo, rev)', 'profile_at.typed_in(repo)', 'json.loads(other_text)'):
        assert not readers(ast.parse(call), calls, owners)


def test_delivery_scan_sees_a_planted_raw_verdict_reader():
    calls, owners, _ = FACTS["delivery verdict"]
    assert readers(ast.parse("found = authorization.results(stores, git, wt, cfg, tree, base, env)"), calls, owners)
