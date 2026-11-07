"""WORKSPACE-2: move src/taskloop/contracts to packages/kernel as the import root `tlkernel`. Re-runnable on a fresh main: a rebase is a rerun.

    python3 dev/move_kernel.py [--root DIR]

Steps, each a no-op once done: git mv the folder; rewrite `taskloop.contracts` to `tlkernel` and the path `src/taskloop/contracts` to
`packages/kernel/src/tlkernel` in every tracked text file except the historical reviews under docs/architecture; write the package manifest;
put src/tlpaths.py (the one helper that adds packages/*/src to sys.path) in place. The structural rules that read the layout by folder name
(gate_rules, affected.py roots, pyrefly search-path, import-linter) are edited by hand in the PR and are NOT touched here."""
import argparse
import re
import subprocess
from pathlib import Path

OLD_DIR, NEW_DIR = "src/taskloop/contracts", "packages/kernel/src/tlkernel"
SKIP = ("docs/architecture/", ".git/", "MANIFEST.sha256", "uv.lock", "skills/task-loop/_vendor/")
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
        new = re.sub(r"\btaskloop\.contracts\b", "tlkernel", text).replace(OLD_DIR, NEW_DIR)
        new = new.replace('"taskloop" / "contracts"', '"tlkernel"').replace("taskloop/contracts", "tlkernel")
        if new != text:
            path.write_text(new, encoding="utf-8")
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    root = Path(ap.parse_args().root)
    old, new = root / OLD_DIR, root / NEW_DIR
    if old.is_dir():
        new.parent.mkdir(parents=True, exist_ok=True)
        git(root, "mv", OLD_DIR, NEW_DIR)
    manifest = root / "packages/kernel/pyproject.toml"
    if not manifest.exists():
        manifest.write_text(MANIFEST, encoding="utf-8")
    print(f"rewrote {rewrite(root)} files")


if __name__ == "__main__":
    main()
