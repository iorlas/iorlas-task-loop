"""Move the store Protocols to tlkernel; rerun after rebasing with --root DIR.

Preflight every Python importer before writing. Unsupported imports abort the move.
Uses git mv when the index is writable, otherwise a filesystem rename (git detects it).
"""
import argparse
import re
import subprocess
from pathlib import Path

OLD = "taskloop" + ".stores.api"
NEW = "tlkernel.storeapi"
SOURCE = "src/taskloop/stores/api.py"
TARGET = "packages/kernel/src/tlkernel/storeapi.py"


def plan(root: Path) -> tuple[list[tuple[Path, str]], list[str]]:
    edits, errors = [], []
    for folder in ("src", "packages", "tests", "dev", "skills"):
        for path in sorted((root / folder).rglob("*.py")):
            if "_vendor" in path.parts or path.resolve() == Path(__file__).resolve():
                continue
            text = path.read_text()
            new = re.sub(rf"(?m)^(\s*from ){re.escape(OLD)}( import\b)", rf"\g<1>{NEW}\2", text)
            alias = re.search(r"from\s+taskloop\.stores\s+import\s*\([^)]*\bapi\b", new)
            if alias:
                errors.append(f"{path.relative_to(root)}: unsupported parenthesized api import")
            for n, line in enumerate(new.splitlines(), 1):
                if OLD in line or re.search(r"from\s+taskloop\.stores\s+import\s+.*\bapi\b", line):
                    errors.append(f"{path.relative_to(root)}:{n}: unsupported reference: {line.strip()}")
            if new != text:
                edits.append((path, new))
    return edits, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root.resolve()
    edits, errors = plan(root)
    source, target = root / SOURCE, root / TARGET
    if source.exists() and target.exists():
        errors.append(f"both {SOURCE} and {TARGET} exist")
    if not source.exists() and not target.exists():
        errors.append(f"neither {SOURCE} nor {TARGET} exists")
    if errors:
        raise SystemExit("No files written:\n" + "\n".join(errors))
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        moved = subprocess.run(["git", "mv", SOURCE, TARGET], cwd=root, capture_output=True, text=True, check=False)
        if moved.returncode:
            print(f"git mv unavailable: {moved.stderr.strip()}; using rename")
            source.rename(target)
    for path, text in edits:
        (target if path == source else path).write_text(text)
    text = target.read_text().replace(
        'Logic depends on these; `real.py` backs them with files, `memory.py` with dicts and lists.',
        'Logic depends on these; store implementations back them with persistent state or in-memory records.',
    )
    target.write_text(text)
    print(f"rewrote {len(edits)} importers; store Protocols live at {TARGET}")


if __name__ == "__main__":
    main()
