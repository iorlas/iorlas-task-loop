"""WORKSPACE-2: move src/taskloop/contracts to packages/kernel as the import root `tlkernel`.
Re-runnable on a fresh main: a rebase is a rerun.

    python3 dev/move_kernel.py [--root DIR]

Steps, each a no-op once done: git mv the folder; rewrite the module name and the path in every tracked text file except the historical
reviews under docs/architecture; move the package's lint file to the package root; write the package manifest; apply EDITS (the places that
name the layout by folder or import form). src/tlpaths.py (the one helper that adds packages/*/src to sys.path) is a file of the PR,
not made here.
Line lengths the longer names push over the lint limit, and tests that read the layout by folder name, are fixed by hand in the PR."""
import argparse
import re
import shutil
import subprocess
from pathlib import Path

OLD_DIR, NEW_DIR = "src/taskloop/contracts", "packages/kernel/src/tlkernel"
OLD_MOD, NEW_MOD = "taskloop" + ".contracts", "tlkernel"  # spelled apart so this file does not rewrite itself
SKIP = ("dev/move_kernel.py", "docs/architecture/", ".git/", "MANIFEST.sha256", "uv.lock", "skills/task-loop/_vendor/")
TEXT = {".py", ".md", ".toml", ".json", ".yml", ".yaml", ".cfg", ".txt", ".importlinter", ".sh", ""}
MANIFEST = '''[project]
name = "tlkernel"
version = "0"
description = "The contracts every stage speaks: records, ids, enums, ports. Imports nothing of ours."
requires-python = ">=3.15"
dependencies = ["msgspec"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tlkernel"]
'''
PATHS_IMPORT = "import tlpaths  # noqa: F401  (every workspace package's src/ on sys.path)\n"
EDITS = (  # (file, old, new)
    (
        'src/taskloop/app/wire/doctor.py',
        'from taskloop import contracts\n',
        'import tlkernel as contracts\n',
    ),
    (
        'packages/dash/src/tldash/cli/dash.py',
        'from taskloop import contracts\n',
        'import tlkernel as contracts\n',
    ),
    (
        'src/taskloop/__init__.py',
        (
            'import sys\n'
            'from pathlib import Path\n'
        ),
        (
            'import sys\n'
            'from pathlib import Path\n'
            '\n'
            "import tlpaths  # noqa: F401  (every workspace package's src/ on sys.path)\n"
        ),
    ),
    (
        'src/taskloop/__init__.py',
        (
            '    sys.set_lazy_imports_filter(lambda importer, name, fromlist=None: name.partition(".")[0] in '
            '("taskloop", "tldash", "tl"))'
        ),
        (
            '    ours = ("taskloop", "tldash", "tlkernel", "tl")\n'
            '    sys.set_lazy_imports_filter(lambda importer, name, fromlist=None: name.partition(".")[0] in ours)'
        ),
    ),
    (
        '.importlinter',
        (
            '    tldash\n'
            '    msgspec\n'
        ),
        (
            '    tldash\n'
            '    tlkernel\n'
            '    msgspec\n'
        ),
    ),
    (
        'ruff.toml',
        'target-version = "py315"\n',
        (
            'target-version = "py315"\n'
            'src = ["src", "packages/kernel/src", "packages/testkit/src"]\n'
        ),
    ),
    (
        'pyrefly.toml',
        'search-path = ["src",',
        'search-path = ["src", "packages/kernel/src", "packages/testkit/src",',
    ),
    (
        'pyrefly.toml',
        'project-includes = ["src",',
        'project-includes = ["src", "packages",',
    ),
    (
        'dev/affected.py',
        (
            'ROOTS = {"src": "src", "tests": "tests", "dev": "dev", "vendor": "skills/task-loop/_vendor", "tl": '
            '"skills/task-loop"}'
        ),
        (
            'ROOTS = {"src": "src", "kernel": "packages/kernel/src", "tests": "tests", "dev": "dev", "vendor": '
            '"skills/task-loop/_vendor",\n'
            '         "tl": "skills/task-loop"}'
        ),
    ),
    (
        'dev/affected.py',
        (
            'VISIBLE = {"src": ("src", "vendor"), "tests": ("tests", "dev", "src", "vendor"), "dev": ("dev", '
            '"src", "vendor"), "vendor": ("vendor",),\n'
            '           "tl": ("src", "vendor")}'
        ),
        (
            'VISIBLE = {"src": ("src", "kernel", "vendor"), "tests": ("tests", "dev", "src", "kernel", "vendor"),\n'
            '           "dev": ("dev", "src", "kernel", "vendor"), "kernel": ("kernel", "vendor"), "vendor": ("vendor",),\n'
            '           "tl": ("src", "kernel", "vendor")}'
        ),
    ),
    (
        'justfile',
        'PYTHONPATH=src:skills/task-loop/_vendor uv tool run',
        'PYTHONPATH=src:packages/kernel/src:skills/task-loop/_vendor uv tool run',
    ),
    (
        'dev/killpoints.py',
        (
            '    from tlkernel.kinds import Kind  # noqa: PLC0415\n'
            '    from tlkernel import closeeffects as fx'
        ),
        (
            '    import tlpaths  # noqa: F401, PLC0415\n'
            '    from tlkernel.kinds import Kind  # noqa: PLC0415\n'
            '    from tlkernel import closeeffects as fx'
        ),
    ),
    (
        'tests/rules/test_env_below_edge.py',
        "  # the owner of os.environ, and the dashboard's edge",
        "  # os.environ's owner, the dashboard's edge",
    ),
    (
        'tests/rules/test_selection_mutations.py',
        (
            '    modules = [p for p in repo.trees if p.startswith("packages/kernel/src/tlkernel/") and '
            'p.count("/") == 3 and not p.endswith("__init__.py")]'
        ),
        (
            '    modules = [p for p in repo.trees\n'
            '               if p.startswith("packages/kernel/src/tlkernel/") and p.count("/") == 4 and not '
            'p.endswith("__init__.py")]'
        ),
    ),
    (
        'dev/killpoints.py',
        '    from tlkernel.checkpoint import Checkpoint  # noqa: PLC0415\n',
        (
            '    import tlpaths  # noqa: F401, PLC0415\n'
            '    from tlkernel.checkpoint import Checkpoint  # noqa: PLC0415\n'
        ),
    ),
    (
        'tests/dash/test_dash_version.py',
        'dash.CONTRACTS.name == "contracts"',
        'dash.CONTRACTS.name == "tlkernel"',
    ),
    (
        'tests/domain/test_lane_policy.py',
        '{"dataclasses", "typing", "taskloop", "__future__", "collections"}',
        '{"dataclasses", "typing", "taskloop", "tlkernel", "__future__", "collections"}',
    ),
    (
        'tests/rules/test_envvars.py',
        'CODE = tuple((ROOT / "src").rglob("*.py"))',
        'CODE = (*(ROOT / "src").rglob("*.py"), *(ROOT / "packages/kernel/src").rglob("*.py"))',
    ),
    (
        'dev/reach.py',
        (
            '    parts = path.split("/")\n'
            '    if parts[0] != "src":'
        ),
        (
            '    parts = path.split("/")\n'
            '    if parts[:3] == ["packages", "kernel", "src"]:\n'
            '        return "kernel"\n'
            '    if parts[0] != "src":'
        ),
    ),
    (
        'tests/rules/arch_rules.py',
        (
            '    for path in py_files(root, ("src", "skills", "dev")):\n'
            '        parts = path.relative_to(root).with_suffix("").parts\n'
            '        if parts[0] == "src":\n'
            '            parts = parts[1:]'
        ),
        (
            '    for path in py_files(root, ("src", "packages/kernel/src", "skills", "dev")):\n'
            '        parts = path.relative_to(root).with_suffix("").parts\n'
            '        if parts[0] == "src":\n'
            '            parts = parts[1:]\n'
            '        elif parts[:3] == ("packages", "kernel", "src"):\n'
            '            parts = parts[3:]'
        ),
    ),
    (
        'justfile',
        'for p in packages/*/; do uv run',
        'for p in packages/*/; do [ -d "$p/tests" ] || continue; uv run',
    ),
    (
        'justfile',
        'for p in $(python3 dev/packages.py); do uv run',
        'for p in $(python3 dev/packages.py); do [ -d "packages/$p/tests" ] || continue; uv run',
    ),
    (
        'dev/hostban_mutation.py',
        '"PYTHONPATH": "src:skills',
        '"PYTHONPATH": "src:packages/kernel/src:skills',
    ),
    (
        'tests/rules/test_stage_parts.py',
        (
            '    src = Path(__file__).resolve().parents[2] / "src"\n'
            '    names = set()\n'
            '    for package in ("taskloop", "tldash"):\n'
            '        for path in (src / package).rglob("*.py"):'
        ),
        (
            '    src = Path(__file__).resolve().parents[2] / "src"\n'
            '    names = set()\n'
            '    for root in (src / "taskloop", src / "tldash", src.parent / "packages/kernel/src/tlkernel"):\n'
            '        for path in root.rglob("*.py"):'
        ),
    ),
    (
        'tests/plan/brief_cases.py',
        'FULL = {"id": "t-1", "title": "Add f", ',
        'FULL: dict[str, object] = {\n        "id": "t-1", "title": "Add f", ',
    ),
    (
        'tests/plan/brief_cases.py',
        'BARE = {',
        'BARE: dict[str, object] = {',
    ),
    (
        'tests/plan/brief_cases.py',
        'CASES = {',
        'CASES: dict[str, tuple[dict[str, object], list[dict[str, str]], bool]] = {',
    ),
    (
        'packages/kernel/src/tlkernel/delegateport.py',
        (
            'class Probe(Protocol):\n'
            '    def up(self) -> bool | None: ...'
        ),
        (
            'class Probe(Protocol):\n'
            '    @property\n'
            '    def hosts(self) -> tuple[str, ...]: ...\n'
            '\n'
            '    def up(self) -> bool | None: ...'
        ),
    ),
)


def git(root: Path, *argv: str) -> str:
    return subprocess.run(["git", *argv], cwd=root, capture_output=True, text=True, check=True).stdout


def rewrite(root: Path) -> int:
    """The files whose text names the old module or path, rewritten. -> how many."""
    n = 0
    for name in git(root, "ls-files").split("\n"):
        path = root / name
        if not name or name.startswith(SKIP) or path.suffix not in TEXT or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        new = re.sub(rf"\b{re.escape(OLD_MOD)}\b", NEW_MOD, text)
        new = new.replace('"src" / "taskloop" / "contracts"', '"packages" / "kernel" / "src" / "tlkernel"')
        new = new.replace(OLD_DIR, NEW_DIR).replace("taskloop/contracts", "tlkernel")
        if new != text:
            path.write_text(new, encoding="utf-8")
            n += 1
    return n


LIMIT = 140
LONG = "packages/kernel/src/tlkernel/"


def shorten(root: Path) -> list[str]:
    """The new path is 6 characters longer than the old, so a few comment and docstring lines pass the lint limit: name the file by its
    package-relative path (`tlkernel/x.py`) there. A line with the path in quotes (code) is left alone. -> the lines still too long."""
    left = []
    for name in git(root, "ls-files", "*.py").split("\n"):
        path = root / name
        if not name or name.startswith(SKIP) or not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8").split("\n")
        for i, line in enumerate(lines):
            if len(line) > LIMIT and LONG in line and '"' + LONG not in line and "'" + LONG not in line:
                lines[i] = line.replace(LONG, "tlkernel/")
        path.write_text("\n".join(lines), encoding="utf-8")
        left += [f"{name}:{i + 1}" for i, line in enumerate(lines) if len(line) > LIMIT]
    return left


def edit(root: Path) -> int:
    n = 0
    dash = root / "packages/dash/src/tldash/__init__.py"
    text = dash.read_text(encoding="utf-8") if dash.exists() else ""
    if text and PATHS_IMPORT not in text:
        i = text.index('"""', 3) + 3
        dash.write_text((text[:i] + "\n" + PATHS_IMPORT + text[i:]).rstrip() + "\n", encoding="utf-8")
        n += 1
    for name, old, new in EDITS:
        path = root / name
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        if old in text and new not in text:
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    root = Path(ap.parse_args().root)
    new = root / NEW_DIR
    if (root / OLD_DIR).is_dir():
        if new.exists() and not git(root, "ls-files", NEW_DIR).strip():
            shutil.rmtree(new)  # left-over ignored files (__pycache__): git mv would nest the folder inside it
        new.parent.mkdir(parents=True, exist_ok=True)
        git(root, "mv", OLD_DIR, NEW_DIR)
    inner = new / "ruff.toml"  # the package's lint file sits at the package root and extends the root's
    if inner.exists():
        text = re.sub(r'extend = "(\.\./)+ruff.toml"', 'extend = "../../ruff.toml"', inner.read_text(encoding="utf-8"))
        (root / "packages/kernel/ruff.toml").write_text(text, encoding="utf-8")
        git(root, "rm", "-qf", "--", str(inner.relative_to(root)))
    manifest = root / "packages/kernel/pyproject.toml"
    if not manifest.exists():
        manifest.write_text(MANIFEST, encoding="utf-8")
    print(f"rewrote {rewrite(root)} files, {edit(root)} config edits")
    pin = re.search(r'^ruff = "([^"]+)"', (root / "mise.toml").read_text(encoding="utf-8"), re.M)
    if pin:  # the import blocks: tlkernel sorts after taskloop, and `from taskloop import contracts` became a plain import
        subprocess.run(["uv", "tool", "run", f"ruff@{pin.group(1)}", "check", "--select", "I", "--fix", "-q", "."], cwd=root, check=False)
    shorten(root)
    subprocess.run(["uv", "lock", "-q"], cwd=root, check=False)  # tlkernel is a new workspace member


if __name__ == "__main__":
    main()
