#!/usr/bin/env python3
"""HOSTBAN mutation proof (tl-e5t0.61): seed one violation per guard in a converted stage and show the guard fail; the tree is restored.

    uv run python dev/hostban_mutation.py

Guards: the import-linter contract `converted-stages-take-no-host` (an import of app.run), ruff ANN401 through the stage's ruff.toml
(`host: Any`), and the name guard of tests/rules/test_host_ban.py (`self.e = host`). Exit 1 when a guard lets its violation through.
Real tools, a few seconds: not part of `just test`."""
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "packages" / "work" / "src" / "tlwork" / "look"
SEED = STAGE / "zz_hostban_seed.py"
PINS = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))["tools"]


def run(argv: list[str], cwd: Path) -> tuple[int, str]:
    roots = ["src", *(p.relative_to(ROOT).as_posix() for p in sorted(ROOT.glob("packages/*/src"))), "skills/task-loop/_vendor"]
    env = {**os.environ, "PYTHONPATH": ":".join(roots)}
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False, env=env)
    return done.returncode, done.stdout + done.stderr


def seeded(text: str, argv: list[str], cwd: Path) -> tuple[int, str]:
    SEED.write_text(text, encoding="utf-8")
    try:
        return run(argv, cwd)
    finally:
        SEED.unlink(missing_ok=True)


def main() -> int:
    ruff = ["uv", "tool", "run", f"ruff@{PINS['ruff']}", "check", "--no-cache", "zz_hostban_seed.py"]
    lint = ["uv", "tool", "run", "--with", "msgspec", "--from", f"import-linter@{PINS['pipx:import-linter']}", "lint-imports"]
    cases = [
        ("imports", seeded("from taskloop.app.run import engine  # seeded\n", lint, ROOT), ("A converted stage imports no host", "BROKEN")),
        ("types", seeded("from typing import Any\n\n\ndef f(host: Any) -> None: ...\n", ruff, STAGE), ("ANN401",)),
    ]
    sys.path[:0] = [str(ROOT / "tests")]
    from rules.host_ban import host_problems  # noqa: PLC0415

    names = host_problems("class A:\n    def __init__(self, host):\n        self.e = host\n")
    bad = 0
    for guard, (rc, out), needle in cases:
        ok = rc != 0 and all(n in out for n in needle)
        print(f"{guard:8} {'FAILED as it should' if ok else 'LET THE VIOLATION THROUGH'} (exit {rc})")
        bad += not ok
    print(f"{'names':8} {'FAILED as it should' if names else 'LET THE VIOLATION THROUGH'} {names}")
    bad += not names
    clean_rc, _ = run(lint, ROOT)
    print(f"clean tree: import-linter exit {clean_rc}")
    return 1 if bad or clean_rc else 0


if __name__ == "__main__":
    sys.exit(main())
