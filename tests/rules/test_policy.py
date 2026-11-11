"""Retain static caps and disallow hidden baseline or process imports."""

import ast
import io
import re
import tokenize
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FILES = sorted(path for folder in ("src", "tests") for path in (ROOT / folder).rglob("*.py"))


def code_lines(source: str, tree: ast.Module) -> set[int]:
    """Count nonblank, noncomment, nondocstring lines as in the baseline policy."""
    ignored = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER}
    lines: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type not in ignored:
            lines.update(range(token.start[0], token.end[0] + 1))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                lines.difference_update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


@pytest.mark.parametrize("path", FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_source_policy(path: Path) -> None:
    source = path.read_text()
    tree = ast.parse(source)
    limits = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["shelf-size"]
    lines = code_lines(source, tree)
    cap = limits["test-file"] if path.is_relative_to(ROOT / "tests") else limits["code-file"]
    assert len(lines) <= cap, path
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno, *[decorator.lineno for decorator in node.decorator_list]])
            assert len(lines & set(range(start, (node.end_lineno or node.lineno) + 1))) <= limits["function"], node.name
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"Any", "cast"}, (path, node.lineno)
        if isinstance(node, ast.Name):
            assert node.id not in {"Any", "cast"}, (path, node.lineno)
        if isinstance(node, ast.ImportFrom):
            assert all(alias.name not in {"Any", "cast"} for alias in node.names)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            assert all(name.split(".")[0] not in {"subprocess", "tlkernel", "tltestkit", "delegate"} for name in names)
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            assert not any(marker in token.string for marker in ("type: ignore", "pyrefly: ignore", "noqa"))


def test_caps_cannot_be_relaxed() -> None:
    limits = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["shelf-size"]
    assert limits == {"code-file": 400, "function": 80, "test-file": 800}



# Every SQL write in the source, by (verb, table) -> the one module allowed to issue it. Anything unlisted is refused.
WRITERS = {
    ("CREATE TABLE", "slot"): "factory_schema.py",
    ("CREATE TABLE", "reservation"): "factory_schema.py",
    ("CREATE TABLE", "attempt"): "factory_schema.py",
    ("CREATE TABLE", "execution"): "factory_schema.py",
    ("CREATE TABLE", "verification"): "factory_schema.py",
    ("CREATE TABLE", "slot_release"): "factory_schema.py",
    ("CREATE TABLE", "published_branch"): "factory_schema.py",
    ("INSERT", "slot"): "slots.py",
    ("INSERT", "reservation"): "admit.py",
    ("INSERT", "attempt"): "admit.py",
    ("UPDATE", "reservation"): "admit_chain.py",  # a repeat's takeover
    ("UPDATE", "slot"): "admit.py",
    ("INSERT", "slot_release"): "slot_release.py",
    ("UPDATE", "slot_release"): "slot_release.py",
    ("DELETE FROM", "reservation"): "slot_release.py",
    ("INSERT", "published_branch"): "publish.py",
    ("INSERT", "execution"): "attempt_store.py",
    ("INSERT", "verification"): "attempt_store.py",
    ("UPDATE", "attempt"): "attempt_store.py",  # also the deadline renewal after a reboot, in the entry registration's write
    ("UPDATE", "execution"): "attempt_store.py",
}
WRITE = re.compile(
    r"\b(CREATE\s+TABLE|(?:INSERT|REPLACE)(?:\s+OR\s+\w+)?\s+INTO|UPDATE(?:\s+OR\s+\w+)?|DELETE\s+FROM)\s+(\w+)", re.IGNORECASE
)


def sql_writes() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for path in (ROOT / "src" / "taskloop").glob("*.py"):
        for match in WRITE.finditer(path.read_text()):
            verb = " ".join(match.group(1).upper().split())
            kind = "INSERT" if verb.startswith(("INSERT", "REPLACE")) else verb.split()[0] if verb.startswith("UPDATE") else verb
            found.add((kind, match.group(2).lower(), path.name))
    return found


def test_every_sql_write_has_its_one_owner() -> None:
    found = sql_writes()
    assert {(kind, table): owner for kind, table, owner in found} == WRITERS
    assert len(found) == len(WRITERS), sorted(found)


@pytest.mark.parametrize(
    "statement",
    ["INSERT INTO slot(a) VALUES (1)", "REPLACE INTO reservation VALUES (1)", "delete from attempt", "UPDATE OR ABORT slot SET a=1"],
)
def test_write_pattern_catches_spelling_variants(statement: str) -> None:
    assert WRITE.search(statement) is not None


# The remote and ref writes below (fetch, sync, the other pushes, branch and remote-ref deletion) have no owner: unused.
GIT_WRITES = frozenset({
    "stage", "stage_tracked", "record", "take_branch", "park", "push", "fetch", "sync", "delete_remote_at", "push_refspecs",
    "push_request", "push_lease", "delete_branch",
})


def git_writers() -> set[tuple[str, str]]:
    """Every use of a Git write on a checkout (`GIT_WRITES`) in the factory source, by module: a call or reference of
    that attribute on any receiver, a bare call of that name, or the name as a string (`getattr(slot, "record")`). Its
    limit: a name built at runtime (`getattr(slot, "re" + "cord")`) or a write through another library API is not seen."""
    found: set[tuple[str, str]] = set()
    for path in (ROOT / "src" / "taskloop").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            called = node.func if isinstance(node, ast.Call) else None
            name = (
                node.attr if isinstance(node, ast.Attribute)
                else called.id if isinstance(called, ast.Name)
                else node.value if isinstance(node, ast.Constant) and isinstance(node.value, str)
                else None
            )
            if name in GIT_WRITES:
                found.add((name, path.name))
    return found


def test_only_the_commit_prepare_release_and_publish_modules_write_git() -> None:
    expected = {
        ("stage", "factory_commit.py"), ("record", "factory_commit.py"), ("take_branch", "prepare.py"), ("park", "prepare.py"),
        ("park", "slot_release.py"), ("push", "publish.py"),
    }
    assert git_writers() == expected


def bd_importers() -> set[str]:
    """Every factory module that imports the tracker client `Bd` (from `beads_client` or a submodule, or the module itself
    to reach `beads_client.Bd`)."""
    found: set[str] = set()
    for path in (ROOT / "src" / "taskloop").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "beads_client":
                found.update(path.name for alias in node.names if alias.name in {"Bd", "client", "*"})
            if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "beads_client" for alias in node.names):
                found.add(path.name)
    return found


def test_only_composition_constructs_the_tracker_client() -> None:
    """The tracker's writes (claim, unclaim, heartbeat) have one wiring owner."""
    assert bd_importers() == {"composition.py"}


SIGNAL_USES = frozenset({"signal", "SIGINT", "SIG_IGN", "default_int_handler", "getsignal"})
# Sending or timing signals, under any receiver (`os.kill`, `signal.alarm`, `proc.kill`): no factory source or test uses one.
SIGNALLING = frozenset({
    "kill", "killpg", "alarm", "setitimer", "pthread_kill", "pthread_sigmask", "set_wakeup_fd", "pidfd_send_signal",
    "raise_signal", "siginterrupt", "sigwait", "sigtimedwait",
})


def signal_uses(path: Path) -> tuple[set[str], set[str], set[str]]:
    """In one file: how `signal` or `_signal` is imported (`import`, `alias`, `from`), every dynamic import
    (`import_module`, `__import__`), and every signalling name used as an attribute or a bare name."""
    imports: set[str] = set()
    dynamic: set[str] = set()
    signalling: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in {"signal", "_signal"}:
                    imports.add("import" if alias.name == "signal" and alias.asname is None else "alias")
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in {"signal", "_signal"}:
            imports.add("from")
        name = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else None
        if name in {"import_module", "__import__"}:
            dynamic.add(name)
        if name in SIGNALLING:
            signalling.add(name)
    return imports, dynamic, signalling


def test_the_one_signal_owner_installs_only_a_sigint_handler_and_nothing_sends_a_signal() -> None:
    """CLAUDE.md's one exception: only `interrupts.py` imports `signal`, plainly (no alias, no `from`, no `_signal`, no
    dynamic import anywhere), and uses only what installs and restores a SIGINT handler; no factory source or test sends
    or times a signal (`SIGNALLING`), and tests never import `signal` (so never install a handler)."""
    owner = ROOT / "src" / "taskloop" / "interrupts.py"
    for path in FILES:
        imports, dynamic, signalling = signal_uses(path)
        assert imports == ({"import"} if path == owner else set()), path
        assert dynamic == signalling == set(), path
    tree = ast.parse(owner.read_text())
    used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "signal"}
    assert used == SIGNAL_USES
    assert not any(isinstance(node, ast.Import) and any(alias.name == "os" for alias in node.names) for node in ast.walk(tree))
