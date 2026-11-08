"""Move land into its workspace member; preflight all writes, rerun with --root DIR."""

import argparse
import ast
import os
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

APP = "taskloop" + ".app.land"
DOMAIN = "taskloop" + ".domain.land"
TARGET = "packages/land/src/tlland"
def module_name(name: str) -> str:
    return name.replace(DOMAIN, "tlland.domain").replace(APP, "tlland")


def selected(node: ast.ImportFrom) -> tuple[str, list[ast.alias]]:
    if node.module in {APP, DOMAIN} or (node.module or "").startswith((APP + ".", DOMAIN + ".")):
        return module_name(node.module or ""), node.names
    if node.module in {"taskloop.app", "taskloop.domain"}:
        return ("tlland" if node.module == "taskloop.app" else "tlland.domain"), [a for a in node.names if a.name == "land"]
    return "", []


def discover(root: Path) -> dict[Path, str]:
    texts = {}
    for folder in ("src", "packages", "tests", "dev", "skills"):
        for p in sorted((root / folder).rglob("*.py")):
            if {"_vendor", "__pycache__", ".venv"}.intersection(p.relative_to(root).parts) or p.name.startswith(("carve_", "move_")):
                continue
            texts[p] = p.read_text()
    return texts


def surface(root: Path, texts: dict[Path, str]) -> list[str]:
    """Measure actual leaf imports outside the new package."""
    leaves = set()
    for p, text in texts.items():
        if any(p.is_relative_to(root / d) for d in
               ("src/taskloop/app/land", "src/taskloop/domain/land", "packages/land")):
            continue
        for n in ast.walk(ast.parse(text)):
            if isinstance(n, ast.ImportFrom):
                module, aliases = selected(n)
                if (n.module or "").startswith("tlland"):
                    module, aliases = n.module or "", n.names
                if not aliases:
                    continue
                if module in {"tlland", "tlland.domain"}:
                    leaves.update((module + "." + a.name).removeprefix("tlland.") for a in aliases)
                else:
                    leaves.add(module.removeprefix("tlland."))
            elif isinstance(n, ast.Import):
                leaves.update(module_name(a.name).removeprefix("tlland.") for a in n.names
                              if a.name.startswith((APP + ".", DOMAIN + ".", "tlland.")))
    return sorted(leaves | {"testing", "contracts"})


def rewrite(text: str) -> str:
    return text.replace(DOMAIN, "tlland.domain").replace(APP, "tlland")


def test_moves(root: Path, texts: dict[Path, str], moves: dict[Path, Path]) -> None:
    allowed = sys.stdlib_module_names | {"tlland", "tlkernel", "tlgate", "tlslots", "tltestkit", "pytest", "msgspec"}
    allowed |= {p.name for p in (root / "skills/task-loop/_vendor").iterdir() if p.is_dir()}
    for p, text in texts.items():
        if not p.is_relative_to(root / "tests/land") or p.name == "__init__.py":
            continue
        imports = []
        for n in ast.walk(ast.parse(text)):
            if isinstance(n, ast.Import):
                imports.extend(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                imports.append(module_name(n.module))
        if all(name.split(".")[0] in allowed for name in imports):
            moves[p] = root / "packages/land/tests" / p.relative_to(root / "tests/land")


def config(path: str, text: str, leaves: list[str] | tuple[()] = ()) -> str:
    """Mechanical rule tables and source paths; no ratchet allowances."""
    if path in {"ruff.toml", "pyrefly.toml"} and '"packages/land/src"' not in text:
        text = text.replace('["src",', '["src", "packages/land/src",')
    if path == "dev/reach.py":
        text = text.replace('{"dash", "kernel",', '{"land", "dash", "kernel",')
    if path == "tests/rules/test_package_surface.py" and '"tlland"' not in text:
        text = text.replace("PACKAGE_ONLY = {", "PACKAGE_ONLY = {\n    \"tlland\": " + repr(tuple(leaves)) + ",", 1)
    if path == "tests/rules/package_tests.py" and '"land": ("tests/land",)' not in text:
        text = text.replace("\nINTEGRATION = {", '\nINTEGRATION = {"land": ("tests/land",), ', 1)
    if path == "tests/rules/closure_ratchet.py":
        text = text.replace('\n                   and not (stage == "tlland" and name.startswith("tlland.domain"))', "")
    if path == "tests/rules/closure_ratchet.py" and '"packages/land/src/tlland"' not in text:
        text = text.replace("TREES = (", 'TREES = ("packages/land/src/tlland", ')
        text = text.replace('.removeprefix("packages/work/")', '.removeprefix("packages/land/").removeprefix("packages/work/")')
        text = text.replace(
            "    for stage in (",
            '    if "tlland" in packages:\n'
            '        stages = [name for name in stages if name != "taskloop.app." + "land"] + ["tlland"]\n'
            "    for stage in (",
        )
        text = text.replace("names = {", 'names = {"tlland": "land", ')
    if path == "tests/rules/test_dash_state_paths.py":
        text = text.replace('        "taskloop/app/land/paths.py",\n', "")
        if 'ROOT / "packages/land/src/tlland/paths.py"' not in text:
            text = text.replace("} | {", '} | {ROOT / "packages/land/src/tlland/paths.py", ')
    if path == "tests/rules/test_engine_order.py":
        text = (
            text.replace('"tlslots": "packages/slots/src",', '"tlland": "packages/land/src", "tlslots": "packages/slots/src",')
            if '"tlland":' not in text
            else text
        )
        text = text.replace('("taskloop.app.",', '("tlland.", "taskloop.app.",') if '("tlland.",' not in text else text
    return followup_config(path, text)


def followup_config(path: str, text: str) -> str:
    """Update fixture roots and the environment scan for the moved member."""
    if path == "tests/rules/test_envvars.py":
        text = text.replace('*(ROOT / "packages/kernel/src").rglob("*.py")',
                            '*(ROOT / "packages/kernel/src").rglob("*.py"), *(ROOT / "packages/land/src").rglob("*.py")')
    if path == "tests/rules/test_layout_lock.py":
        text = text.replace('C: "app/land"', 'C: "packages/land"')
    if path == "tests/rules/real/test_work_boundary.py":
        text = text.replace('.replace("tlasks", "sample")', '.replace("tlasks", "sample").replace("tlland", "sample")')
    if path == "tests/rules/test_reach.py":
        text = text.replace('src/taskloop/app/land/', 'src/taskloop/app/doctor/')
        text = text.replace(APP, 'taskloop.app.doctor')
        text = text.replace('("land", "slots")', '("doctor", "slots")')
        text = text.replace('"from tlland import a', '"from taskloop.app.doctor import a')
    return polish(path, source_paths(path, text))


def polish(path: str, text: str) -> str:
    """Wrap rule fixtures lengthened by the mechanical path rewrite."""
    if path == "dev/reach.py":
        text = text.replace(
            'parts[1] in {"land", "dash", "kernel", "slots", "work", "release"}:',
            'parts[1] in {\n        "land", "dash", "kernel", "slots", "work", "release",\n    }:',
        )
    if path == "tests/rules/test_dash_state_paths.py":
        text = text.replace(
            '} | {ROOT / "packages/land/src/tlland/paths.py", ',
            '} | {\n    ROOT / "packages/land/src/tlland/paths.py",\n    '
        )
    if path == "tests/rules/test_engine_order.py":
        text = text.replace('"tlland": "packages/land/src", "tlslots":', '"tlland": "packages/land/src",\n               "tlslots":')
    if path == "tests/rules/test_reach.py":
        text = text.replace(
            '    assert wide_alone(repo, {"packages/kernel/src/tlkernel/k.py", "src/taskloop/app/doctor/a.py"}, 3)',
            '    assert wide_alone(\n        repo, {"packages/kernel/src/tlkernel/k.py", "src/taskloop/app/doctor/a.py"}, 3,\n    )',
        )
    if path == "tests/rules/test_package_surface.py":
        start = text.find('    "tlland": ')
        if start >= 0:
            end = text.index("\n", start)
            entry = text[start:end]
            text = text[:start] + "\n".join(textwrap.wrap(entry, 115, subsequent_indent="        ",
                                                         break_long_words=False, break_on_hyphens=False)) + text[end:]
    if path == "tests/rules/test_envvars.py":
        text = text.replace(', *(ROOT / "packages/land/src")', ',\n                *(ROOT / "packages/land/src")')
    if path == "tests/rules/real/test_work_boundary.py":
        text = text.replace('    return text.replace("taskloop"', '    return (text.replace("taskloop"')
        text = text.replace('.replace("tlland", "sample")', '\n            .replace("tlland", "sample"))')
    return "\n".join(line.rstrip() for line in text.splitlines()) + ("\n" if text.endswith("\n") else "")


def source_paths(path: str, text: str) -> str:
    if path in {"src/taskloop/domain/land/queue_flake.py", TARGET + "/domain/queue_flake.py"}:
        text = text.replace("from tlgate.domain.retry import retry_allowed", "from tlgate.api import retry_allowed")
    if path == "packages/gate/src/tlgate/api.py" and '"retry_allowed"' not in text:
        text = text.replace(
            "from tlgate.domain import planref", "from tlgate.domain import planref\nfrom tlgate.domain.retry import retry_allowed"
        )
        text = text.replace("__all__ = [", '__all__ = [\n    "retry_allowed",')
    if path == "tests/rules/test_gatepass_rule.py":
        text = text.replace('HOME = SRC / "app" / "land" / "gate.py"', 'HOME = SRC.parents[1] / "packages/land/src/tlland/gate.py"')
    if path == "tests/rules/test_land_asserts_tree.py":
        text = text.replace('/ "src" / "taskloop" / "app" / "land" / "stack.py"', '/ "packages/land/src/tlland/stack.py"')
    if path == "tests/rules/test_queue_terms.py":
        text = text.replace('/ "src" / "taskloop"', '/ "packages/land/src/tlland"')
        text = text.replace(
            '"domain/land/queue*.py", "app/land/queue*.py", "app/land/in_flight*.py"', '"domain/queue*.py", "queue*.py", "in_flight*.py"'
        )
    # Real paths and module strings (patch targets, architecture allow-tables, AST fixtures).
    if not path.startswith(("dev/carve_", "dev/move_", "tests/dev/test_carve_", "tests/dev/test_move_")):
        text = text.replace("src/taskloop/app/land/", TARGET + "/").replace("src/taskloop/domain/land/", TARGET + "/domain/")
        text = text.replace(APP, "tlland").replace(DOMAIN, "tlland.domain")
    return text


def contracts(text: str, root: Path, texts: dict[Path, str]) -> str:
    text = text.replace("    land\n", "").replace(APP, "tlland").replace(DOMAIN, "tlland.domain")
    if "\n    tlland\n" not in text.split("[importlinter:contract:layers]")[0]:
        text = text.replace("root_packages =\n", "root_packages =\n    tlland\n")
    if "[importlinter:contract:package-land-imports-only-the-kernel]" not in text:
        forbidden = sorted(
            p.parent.name
            for p in (root / "packages").glob("*/pyproject.toml")
            if p.parent.name not in {"kernel", "land", "testkit", "rules"}
        )
        text += (
            "\n[importlinter:contract:package-land-imports-only-the-kernel]\n"
            "name = Land imports kernel and declared package APIs only\ntype = forbidden\nsource_modules = tlland\n"
            "forbidden_modules =\n    taskloop\n    delegate\n"
            + "".join("    tl" + p + "\n" for p in forbidden)
            + "allow_indirect_imports = True\nignore_imports =\n"
        )
        for p, body in texts.items():
            if not any(p.is_relative_to(root / folder) for folder in ("src/taskloop/app/land", "src/taskloop/domain/land")):
                continue
            for n in ast.walk(ast.parse(body)):
                if isinstance(n, ast.ImportFrom) and n.module in {"tlgate.api", "tlslots.api"}:
                    part = "domain." if p.is_relative_to(root / "src/taskloop/domain/land") else ""
                    text += f"    tlland.{part}{p.stem} -> {n.module}\n"
    return text


def metadata(root: Path, writes: dict[Path, str]) -> None:
    manifest = (root / "packages/asks/pyproject.toml").read_text().replace("tlasks", "tlland")
    manifest = manifest.replace(
        "Ask admission, owner questions and park rules. Imports only the kernel.", "Land orchestration and pure land domain rules."
    )
    manifest = manifest.replace('dependencies = ["tlkernel"]', 'dependencies = ["tlkernel", "tlgate", "tlslots"]')
    manifest = manifest.replace(
        "[tool.uv.sources]",
        "[tool.uv.sources]\ntlgate = { workspace = true }\ntlslots = { workspace = true }",
    )
    manifest = manifest.replace('dev = ["pytest", "tltestkit"]', 'dev = ["pytest", "tltestkit", "msgspec"]')
    writes[root / "packages/land/pyproject.toml"] = manifest
    writes[root / "packages/land/ruff.toml"] = (
        (root / "packages/gate/ruff.toml").read_text().replace("checks is a converted stage", "land is a converted stage")
    )
    for name in ("workspace.md", "stage-packages.md"):
        p = root / "docs/design" / name
        text = p.read_text()
        line = (
            "\nLand L2a: `packages/land` (`tlland`) owns land app/domain code and isolated tests; "
            "shell integration tests remain in `tests/land`.\n"
        )
        writes[p] = text if line.strip() in text else text + line
    p = root / "docs/design/stage-carves.md"
    writes[p] = p.read_text().replace("| land (.20) |", "| land (.20; L2a code/test carve done) |")


def plan(root: Path) -> tuple[dict[Path, Path], dict[Path, str], list[str]]:
    moves, errors = {}, []
    for source, target in [("src/taskloop/app/land", TARGET), ("src/taskloop/domain/land", TARGET + "/domain")]:
        folder = root / source
        if not folder.exists() and not (root / target / "__init__.py").exists():
            errors.append(f"missing source and target: {source}")
        for p in folder.rglob("*"):
            if "__pycache__" in p.parts:
                continue
            if p.is_file() and p.suffix == ".py" and p.parent == folder:
                moves[p] = root / target / p.name
            else:
                errors.append(f"unsupported source entry: {p}")
    texts = discover(root)
    test_moves(root, {p: rewrite(t) for p, t in texts.items()}, moves)
    leaves = surface(root, {p: t for p, t in texts.items() if p not in moves})
    print("leaf surface:", ", ".join(leaves))
    writes = {}
    for p, text in texts.items():
        new = config(p.relative_to(root).as_posix(), rewrite(text), leaves)
        ast.parse(new)
        if new != text:
            writes[p] = new
    test_moves(root, {p: writes.get(p, text) for p, text in texts.items()}, moves)
    for p in moves:
        if p.is_relative_to(root / "tests/land"):
            body = writes.get(p, texts[p])
            body = body.replace("ROOT = Path(__file__).resolve().parents[2]", "ROOT = Path(__file__).resolve().parents[3]")
            writes[p] = body
    # Test moves were classified after rewriting; relocate their pending writes too.
    writes = {moves.get(p, p): body for p, body in writes.items()}
    errors += [f"both source and target exist: {p}, {q}" for p, q in moves.items() if q.exists()]
    for name in ("ruff.toml", "pyrefly.toml"):
        p = root / name
        writes[p] = config(name, p.read_text())
    writes[root / ".importlinter"] = contracts(
        (root / ".importlinter").read_text(),
        root,
        {p: source_paths(p.relative_to(root).as_posix(), rewrite(t)) for p, t in texts.items()},
    )
    metadata(root, writes)
    for marker in ("__init__.py", "real/__init__.py"):
        writes[root / "packages/land/tests" / marker] = (root / "tests/land" / marker).read_text()
    writes[root / "packages/land/tests/conftest.py"] = (
        '"""Standalone land test scratch fixture."""\n'
        "from collections.abc import Iterator\nfrom pathlib import Path\n\nimport pytest\n\n\n"
        "@pytest.fixture\ndef workdir(tmp_path: Path) -> Iterator[Path]:\n    yield tmp_path\n"
    )
    writes = {p: body for p, body in writes.items() if not p.exists() or p.read_text() != body}
    return moves, writes, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    moves, writes, errors = plan(root)
    tests = sum(p.is_relative_to(root / "tests/land") for p in moves)
    print(f"preflight: {len(moves)} moves ({tests} tests), {len(writes)} rewrites, {len(errors)} unsupported forms")
    if errors:
        raise SystemExit("No files written:\n" + "\n".join(errors))
    if args.preflight:
        return
    for p, q in moves.items():
        q.parent.mkdir(parents=True, exist_ok=True)
        p.rename(q)
    for p, body in writes.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    for name in ("src/taskloop/app/land", "src/taskloop/domain/land"):
        folder = root / name
        if folder.exists():
            shutil.rmtree(folder)
    written = sorted({p for p in (*writes, *moves.values()) if p.suffix == ".py"})
    # Sort only after every real config has been written, including the new member's.
    command = shlex.split(os.environ.get("RUFF", "uv tool run ruff@0.17.2"))
    subprocess.run([*command, "check", "--select", "I001,RUF022", "--fix", "--quiet", *(str(p) for p in written)], cwd=root, check=True)
    subprocess.run(["uv", "lock", "--project", str(root)], check=True)


if __name__ == "__main__":
    main()
