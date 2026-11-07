"""WORKSPACE-2: move src/taskloop/contracts to packages/kernel as the import root `tlkernel`. Re-runnable on a fresh main: a rebase is a rerun.

    python3 dev/move_kernel.py [--root DIR]

Steps, each a no-op once done: git mv the folder; rewrite the module name and the path in every tracked text file except the historical
reviews under docs/architecture; move the package's lint file to the package root; write the package manifest; apply EDITS (the places that
name the layout by folder or import form). src/tlpaths.py (the one helper that adds packages/*/src to sys.path) is a file of the PR, not made
here. Line lengths the longer names push over the lint limit, and tests that read the layout by folder name, are fixed by hand in the PR."""
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
    ("src/taskloop/app/wire/doctor.py", "from taskloop import contracts\n", "import tlkernel as contracts\n"),
    ("src/taskloop_dash/cli/dash.py", "from taskloop import contracts\n", "import tlkernel as contracts\n"),
    ("src/taskloop/__init__.py", "import sys\nfrom pathlib import Path\n", "import sys\nfrom pathlib import Path\n\n" + PATHS_IMPORT),
    ("src/taskloop/__init__.py", '("taskloop", "taskloop_dash", "tl")', '("taskloop", "taskloop_dash", "tlkernel", "tl")'),
    (".importlinter", "    taskloop_dash\n    msgspec\n", "    taskloop_dash\n    tlkernel\n    msgspec\n"),
    ("ruff.toml", 'target-version = "py315"\n', 'target-version = "py315"\nsrc = ["src", "packages/kernel/src", "packages/testkit/src"]\n'),
    ("pyrefly.toml", 'search-path = ["src",', 'search-path = ["src", "packages/kernel/src", "packages/testkit/src",'),
    ("pyrefly.toml", 'project-includes = ["src",', 'project-includes = ["src", "packages",'),
    ("dev/affected.py", 'ROOTS = {"src": "src", ', 'ROOTS = {"src": "src", "kernel": "packages/kernel/src", '),
    ("dev/affected.py",
     'VISIBLE = {"src": ("src", "vendor"), "tests": ("tests", "dev", "src", "vendor"), "dev": ("dev", "src", "vendor"), "vendor": ("vendor",),\n'
     '           "tl": ("src", "vendor")}',
     'VISIBLE = {"src": ("src", "kernel", "vendor"), "tests": ("tests", "dev", "src", "kernel", "vendor"),\n'
     '           "dev": ("dev", "src", "kernel", "vendor"), "kernel": ("kernel", "vendor"), "vendor": ("vendor",), "tl": ("src", "kernel", "vendor")}'),
    ("justfile", "PYTHONPATH=src:skills/task-loop/_vendor uv tool run", "PYTHONPATH=src:packages/kernel/src:skills/task-loop/_vendor uv tool run"),
    ("dev/hostban_mutation.py", '"PYTHONPATH": "src:skills', '"PYTHONPATH": "src:packages/kernel/src:skills'),
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


def edit(root: Path) -> int:
    n = 0
    dash = root / "src/taskloop_dash/__init__.py"
    text = dash.read_text(encoding="utf-8") if dash.exists() else ""
    if text and PATHS_IMPORT not in text:
        i = text.index('"""', 3) + 3
        dash.write_text(text[:i] + "\n" + PATHS_IMPORT + text[i:], encoding="utf-8")
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


if __name__ == "__main__":
    main()
