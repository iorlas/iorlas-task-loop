#!/usr/bin/env python3
"""Kernel layer mutation proof (tl-e5t0.10): seed upward imports and show the lint layer fail; the tree is restored.

    uv run python dev/kernel_layer_mutation.py

Exit 1 when a guard lets its violation through or the clean tree fails.
Real tools, a few seconds: not part of `just test`."""
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "packages" / "kernel" / "src" / "tlkernel" / "zz_kernel_seed.py"
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
    lint = ["uv", "tool", "run", "--with", "msgspec", "--from", f"import-linter@{PINS['pipx:import-linter']}", "lint-imports"]
    cases = [
        ("taskloop", "from taskloop.domain.lanes import policy  # seeded\n"),
        ("dash", "from taskloop_dash import env  # seeded\n"),
        ("delegate", "from delegate import api  # seeded\n"),
    ]
    bad = 0
    for guard, text in cases:
        rc, out = seeded(text, lint, ROOT)
        ok = rc != 0 and all(n in out for n in ("the kernel (tlkernel) imports nothing of ours", "BROKEN"))
        print(f"{guard:8} {'FAILED as it should' if ok else 'LET THE VIOLATION THROUGH'} (exit {rc})")
        bad += not ok
    clean_rc, _ = run(lint, ROOT)
    print(f"clean tree: import-linter exit {clean_rc}")
    return 1 if bad or clean_rc else 0


if __name__ == "__main__":
    sys.exit(main())
