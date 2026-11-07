"""Move dashboard into its workspace member; preflight all writes, rerun with --root DIR."""

import argparse
import ast
import os
import re
import shlex
import subprocess
from pathlib import Path

OLD = "taskloop" + "_dash"
NEW = "tldash"
SOURCE = "src/" + OLD
TARGET = "packages/dash/src/tldash"
HELPERS = ("dashlogs", "dashlive", "factory_index")


def merged(root: Path) -> str:
    """Combine helpers, preserving bodies except the approved live constant rename."""
    imports, bodies = [], []
    for name in HELPERS:
        text = (root / f"tests/support/{name}.py").read_text()
        if name == "dashlive":
            text = re.sub(r"\bT\b", "LIVE_T", text)
        tree = ast.parse(text)
        lines = text.splitlines(keepends=True)
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue
            assert node.end_lineno is not None
            part = "".join(lines[node.lineno - 1 : node.end_lineno])
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if "import support.paths" not in part and part not in imports:
                    imports.append(part)
            else:
                bodies.append(part)
    return (
        '"""Dashboard fixture logs and projection helpers: public testing surface."""\n'
        + "".join(imports)
        + "\n\n"
        + "\n\n\n".join(part.strip("\n") for part in bodies)
        + "\n"
    )


def rename(text: str) -> str:
    text = text.replace(SOURCE, TARGET).replace(OLD, NEW)
    text = text.replace('"src" / "tldash"', '"packages" / "dash" / "src" / "tldash"')
    duplicate = '"packages" / "dash" / "packages" / "dash" / '
    while duplicate in text:
        text = text.replace(duplicate, '"packages" / "dash" / ')
    text = text.replace("support.waits", "tltestkit.waits").replace("from support import waits", "from tltestkit import waits")
    for name in HELPERS:
        text = text.replace(f"from support.{name} import", "from tldash.testing import")
        text = text.replace(f"from support import {name}", f"from tldash import testing as {name}")
        text = text.replace(f"import support.{name}", f"import tldash.testing as {name}")
        text = text.replace(f"support.{name}.", f"{name}.")
    text = text.replace("from tldash.testing import BEAD, STAMP, T,", "from tldash.testing import BEAD, STAMP, LIVE_T as T,")
    return text


def special(path: str, text: str) -> str:
    """Mechanical path and configuration changes after the global name rewrite."""
    if path == "src/taskloop/app/launch/dash.py":
        text = text.replace('DASH: Final = SRC / "tldash"', 'DASH: Final = PLUGIN_ROOT / "packages/dash/src/tldash"')
        text = text.replace("[str(SRC), str(VENDOR), *more]", '[str(SRC), str(PLUGIN_ROOT / "packages/dash/src"), str(VENDOR), *more]')
    if path == TARGET + "/__init__.py" and "find_spec" not in text:
        text = text.replace(
            "import tlpaths  # noqa: F401  (every workspace package's src/ on sys.path)",
            'from importlib.util import find_spec\n\nif find_spec("tlpaths") is not None:\n'
            '    import tlpaths  # noqa: F401  (checkout workspace bootstrap)',
        )
    if path == TARGET + "/__main__.py":
        text = text.replace("parents[2]", "parents[4]")
    if path == "tests/support/paths.py":
        text = text.replace("[SRC, VENDOR,", '[SRC, str(ROOT / "packages/dash/src"), VENDOR,')
    if path == "pyrefly.toml" and '"packages/dash/src"' not in text:
        text = text.replace('search-path = ["src",', 'search-path = ["src", "packages/dash/src",')
    if path == "src/taskloop/app/loop/versions.py" and 'd / "packages/dash/src"' not in text:
        text = text.replace(
            'files += sorted((d / "src").rglob("*.py"))',
            'files += sorted((d / "src").rglob("*.py"))\n    files += sorted((d / "packages/dash/src").rglob("*.py"))',
        )
    if path == "src/taskloop/app/release/selfupdate.py":
        text = text.replace('CODE = ("src", "dev/release.py")', 'CODE = ("src", "packages/dash/src", "dev/release.py")')
    return rule_paths(path, contracts_and_docs(path, tool_paths(path, text)))


def tool_paths(path: str, text: str) -> str:
    """Point the tool configs and the reach map at the package."""
    if path == "dev/reach.py":
        old = ('    if parts[:3] == ["packages", "kernel", "src"]:\n        return "kernel"\n'
               '    if parts[:3] == ["packages", "slots", "src"]:\n        return "slots"\n')
        new = ('    if parts[0] == "packages" and parts[2:3] == ["src"] and parts[1] in {"dash", "kernel", "slots"}:\n'
               '        return parts[1]\n')
        text = text.replace(old, new)
    if path == "tests/rules/test_dash_state_paths.py":
        text = text.replace(', "tldash/paths.py"', "")
        if 'DASH / "paths.py"' not in text:
            text = text.replace('tlslots/paths.py"}', 'tlslots/paths.py", DASH / "paths.py"}')
    if path in ("src/taskloop/app/ruff.toml", "src/taskloop/cli/ruff.toml"):
        text = text.replace('src = ["../.."]  # src/: taskloop and tldash sort as first party, as under the root config',
                            'src = ["../..", "../../../packages/dash/src"]  # shell and dashboard imports are first party')
    if path == "ruff.toml" and '"packages/dash/src"' not in text:
        text = text.replace('src = ["src",', 'src = ["src", "packages/dash/src",')
    return text


def rule_paths(path: str, text: str) -> str:
    """Relocate the rule fixtures with the source and test trees."""
    if path == "tests/rules/test_dash_tests_isolated.py":
        text = text.replace('"tests" / "dash"', '"packages" / "dash" / "tests"').replace("tests/dash/", "packages/dash/tests/")
    if path == "tests/rules/test_layout_lock.py":
        text = text.replace('("' + TARGET + '/page.py", "tldash")', '("' + TARGET + '/page.py", "packages/dash")')
    if path == "tests/dashwire/test_dash_golden.py":
        text = text.replace('Path(__file__).resolve().parents[1] / "dash" / "golden"',
                            'Path(__file__).resolve().parents[2] / "packages" / "dash" / "tests" / "golden"')
    if path == "tests/rules/test_dash_state_paths.py":
        text = text.replace('MAKES_CONFIGDIR = {"env.py", "bind.py"}  # where the config root is taken from the process: everything else',
                            'MAKES_CONFIGDIR = {"env.py", "bind.py", "testing.py"}  # where the config root is made: everything else')
    if path == "tests/rules/package_tests.py" and "VENDORED" not in text:
        text = text.replace("        allowed = own | {\"pytest\"} | sys.stdlib_module_names\n",
                            "        allowed = own | {\"pytest\"} | sys.stdlib_module_names | VENDORED\n")
        vendored = ('# Shelf copies have no manifest: the one undeclared path (docs/design/workspace.md section 4).\n'
                    'VENDORED = {p.name for p in (ROOT / "skills/task-loop/_vendor").iterdir() if p.is_dir()}\n')
        text = text.replace("\n\ndef imports(", "\n" + vendored + "\n\ndef imports(", 1)
    if path == "tests/rules/layout_lock.py":
        text = text.replace('(("src", "tldash"), ("src", "delegate"))', '(("src", "delegate"),)')
    return text


def contracts_and_docs(path: str, text: str) -> str:
    """Update architecture contracts and carve status."""
    if path == ".importlinter" and "contract:package-dash-imports-only-the-kernel]" not in text:
        start = text.index("[importlinter:contract:dash-imports-contracts-only]")
        end = text.index("[importlinter:contract:only-launch-imports-dash]", start)
        text = text[:start] + text[end:]
        text += (
            "\n"
            "[importlinter:contract:package-dash-imports-only-the-kernel]\n"
            "name = The dash package imports the kernel, third parties and delegate.api (its console reader), never the tree or a package\n"
            "type = forbidden\n"
            "source_modules = tldash\n"
            "forbidden_modules =\n"
            "    taskloop\n"
            "    delegate\n"
            "    tlartifacts\n"
            "    tlgate\n"
            "    tlpipeline\n"
            "    tlslots\n"
            "allow_indirect_imports = True\n"
            "ignore_imports =\n"
            "    tldash.readers.logs -> delegate.api\n"
        )
    if path in ("docs/design/workspace.md", "docs/design/stage-packages.md"):
        line = "\nDash is carved into `packages/dash` (`tldash`), with isolated package tests.\n"
        if line.strip() not in text:
            text += line
    return text


def discover(root: Path, helpers_present: bool, deletes: list[Path]) -> dict[Path, str]:
    """Read all supported inputs before any mutation."""
    texts = {}
    for folder in ("src", "packages", "tests", "dev", "skills", "docs/design", "docs/dev", "docs/contracts"):
        for p in (root / folder).rglob("*"):
            if (
                p.is_file()
                and not {"_vendor", "__pycache__", ".venv", ".git"}.intersection(p.parts)
                and p.suffix in {".py", ".toml", ".md", ".js", ".css", ".html", ".txt"}
                and p.name != "move_dash.py"
                and p not in deletes
            ):
                texts[p] = p.read_text()
    for name in (".importlinter", "README.md", "pyrefly.toml", "ruff.toml"):
        texts[root / name] = (root / name).read_text()
    if helpers_present:
        texts[root / TARGET / "testing.py"] = merged(root)
    return texts


def unsupported(tree: ast.AST) -> list[str]:
    """Refuse helper bindings that need semantic review."""
    errors = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "support":
            names = {alias.name for alias in node.names} & {*HELPERS, "waits"}
            if names and len(node.names) != 1:
                errors.append(f"line {node.lineno}: mixed support helper import")
        if (isinstance(node, ast.ImportFrom) and node.module in {f"support.{name}" for name in HELPERS}
                and any(alias.name == "*" for alias in node.names)):
            errors.append(f"line {node.lineno}: helper star import")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {f"support.{name}" for name in HELPERS} and alias.asname:
                    errors.append(f"line {node.lineno}: aliased helper module import")
    return errors


def polish(path: str, text: str) -> str:
    """Wrap lines lengthened by the move and retain import-order annotations."""
    if path == "src/taskloop/app/launch/dash.py":
        text = text.replace('os.pathsep.join([str(SRC), str(PLUGIN_ROOT / "packages/dash/src"), str(VENDOR), *more])',
                            'os.pathsep.join([\n        str(SRC), str(PLUGIN_ROOT / "packages/dash/src"), str(VENDOR), *more,\n    ])')
    if path == "tests/dashwire/test_dash_live.py":
        text = text.replace('ingest,  # noqa: E402', 'ingest,')
        text = text.replace('from tldash.testing import LIVE_T as T\n', 'from tldash.testing import LIVE_T as T  # noqa: E402\n')
    if path == "tests/rules/test_delegate_scope.py":
        text = text.replace('lambda: {"src/taskloop/app/run/x.py", "packages/dash/src/tldash/y.py", "tests/land/test_z.py"})',
                            'lambda: {\n            "src/taskloop/app/run/x.py", "packages/dash/src/tldash/y.py", '
                            '"tests/land/test_z.py",\n        })')
    if path == "tests/rules/test_envvars.py":
        text = text.replace('hits = {str(p.relative_to(ROOT)) for p in (', 'hits = {str(p.relative_to(ROOT))\n                for p in (')
    if path == "tests/rules/test_runstate_rule.py":
        text = text.replace('"packages/dash/src/tldash/readers/logs.py", "packages/dash/src/tldash/views/runfacts.py",',
                            '"packages/dash/src/tldash/readers/logs.py",\n    "packages/dash/src/tldash/views/runfacts.py",')
    return text


def sorted_imports(root: Path, dest: Path, text: str) -> str:
    """Sort renamed imports in memory; RUFF can name an already installed binary."""
    command = shlex.split(os.environ.get("RUFF", "uv tool run ruff@0.17.2"))
    known = ["tldash", "tltestkit"]
    if dest.is_relative_to(root / "packages/dash"):
        known += ["taskloop", "delegate", "tlpaths", "tlkernel", "tltestkit", "tlartifacts", "tlpipeline", "tlgate"]
    ran = subprocess.run(
        [*command, "check", "--select", "I", "--fix", "--stdin-filename", str(dest),
         "--config", f"lint.isort.known-first-party = {known!r}", "-"],
        input=text, text=True, capture_output=True, cwd=root, check=False,
    )
    if ran.returncode:
        raise ValueError(f"{dest}: import sorting failed: {ran.stderr}")
    return polish(dest.relative_to(root).as_posix(), ran.stdout)


def rewrites(root: Path, texts: dict[Path, str], moves: dict[Path, Path], errors: list[str]) -> dict[Path, str]:
    """Compute rewrites and reject malformed Python before writes."""
    writes = {}
    for p, text in texts.items():
        dest = moves.get(p, p)
        new = special(dest.relative_to(root).as_posix(), rename(text))
        if p in moves and "tests/dash" in p.as_posix():
            new = re.sub(r"(ROOT = Path\(__file__\).resolve\(\).parents\[)(\d+)(\])", lambda m: m[1] + str(int(m[2]) + 1) + m[3], new)
            new = new.replace('parents[2] / "' + TARGET, 'parents[3] / "' + TARGET)
        if p.suffix == ".py":
            try:
                tree = ast.parse(text)
                errors.extend(f"{p}: {message}" for message in unsupported(tree))
                ast.parse(new)
                if NEW in new or "tltestkit.waits" in new or "from tltestkit import waits" in new:
                    new = sorted_imports(root, dest, new)
            except (SyntaxError, ValueError, OSError) as exc:
                errors.append(f"{p}: {exc}")
        if new != text or (not dest.exists() and p not in moves):
            writes[dest] = new
    return writes


def member_files(root: Path, writes: dict[Path, str]) -> None:
    """Plan member metadata and the inherited database fixture setup."""
    manifest = (root / "packages/artifacts/pyproject.toml").read_text().replace("tlartifacts", "tldash")
    manifest = manifest.replace(
        "Evidence pictures a run keeps: the store, the keeper with its cap, the picture server and the ask pictures.",
        "Dashboard server, views and static assets.",
    )
    manifest = manifest.replace('dev = ["pytest", "tltestkit"]', 'dev = ["pytest", "tltestkit", "msgspec"]')
    manifest = manifest.replace(
        'pythonpath = ["../../skills/task-loop/_vendor"]',
        '# delegate is the library in this repo (src/delegate): the console reader imports delegate.api, the one import of it\n'
        'pythonpath = ["../../skills/task-loop/_vendor", "../../src"]',
    )
    ruff = ('# The dash serves HTTP and runs threads, so it extends the root config, not the kernel\'s contracts-only one.\n'
            'extend = "../../ruff.toml"\nsrc = ["src"]\n')
    for name, value in (("pyproject.toml", manifest), ("ruff.toml", ruff)):
        p = root / "packages/dash" / name
        if not p.exists() or p.read_text() != value:
            writes[p] = value
    conftest = root / "packages/dash/tests/conftest.py"
    fixture = (
        '"""Declare the dashboard-owned database parts, and the look part its wake tests write through, for isolated tests."""\n'
        "from tlkernel import factorydb\nfrom tlkernel.factoryparts import LOOK\n\nfrom tldash.parts import DASH_PARTS\n\n"
        "factorydb.declare_parts((*DASH_PARTS, LOOK))\n"
    )
    if not conftest.exists():
        writes[conftest] = fixture


def plan(root: Path) -> tuple[dict[Path, Path], dict[Path, str], list[Path], list[str]]:
    moves: dict[Path, Path] = {}
    errors: list[str] = []
    for old, new in ((SOURCE, TARGET), ("tests/dash", "packages/dash/tests")):
        source, target = root / old, root / new
        if source.exists() and target.exists():
            errors.append(f"both source and destination exist: {old}, {new}")
        if not source.exists() and not target.exists():
            errors.append(f"neither source nor destination exists: {old}, {new}")
        for p in source.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                moves[p] = target / p.relative_to(source)
    wait = root / "tests/support/waits.py"
    if wait.exists():
        moves[wait] = root / "packages/testkit/src/tltestkit/waits.py"
    deletes = [root / f"tests/support/{name}.py" for name in HELPERS]
    present = [p.exists() for p in deletes]
    if any(present) and not all(present):
        errors.append("partial helper migration")
    texts = discover(root, all(present), deletes)
    writes = rewrites(root, texts, moves, errors)
    member_files(root, writes)
    for q in moves.values():
        if q.exists():
            errors.append(f"destination already exists: {q}")
    return moves, writes, deletes if all(present) else [], errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root.resolve()
    moves, writes, deletes, errors = plan(root)
    print(f"preflight: {len(moves)} moves, {len(writes)} rewrites, {len(deletes)} merged helpers, {len(errors)} unsupported forms")
    if errors:
        raise SystemExit("No files written:\n" + "\n".join(errors))
    for p, q in moves.items():
        q.parent.mkdir(parents=True, exist_ok=True)
        p.rename(q)
    for p, text in writes.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    for p in deletes:
        p.unlink()
    written = [str(moves.get(p, p)) for p in writes if p.suffix == ".py"]
    # the real config now exists: its first-party sets decide the final import order
    command = shlex.split(os.environ.get("RUFF", "uv tool run ruff@0.17.2"))
    subprocess.run([*command, "check", "--select", "I001", "--fix", "--quiet", *written], cwd=root, check=False)
    subprocess.run(["uv", "lock", "--project", str(root)], check=True)
    for name in (SOURCE, "tests/dash"):
        folder = root / name
        if folder.exists():
            for p in sorted(folder.rglob("*"), reverse=True):
                if p.is_dir() and not any(p.iterdir()):
                    p.rmdir()
            if not any(folder.iterdir()):
                folder.rmdir()


if __name__ == "__main__":
    main()
