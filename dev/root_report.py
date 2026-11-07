"""Report composition-root size and Engine attributes without storing a baseline.

Run with: uv run python dev/root_report.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from rules.root_ratchet import engine_attributes, offenders, totals


def main() -> None:
    counts = totals()
    print(f"root files: {counts['files']}")
    print(f"sloc: {counts['sloc']}")
    print(f"branches: {counts['branch']}")
    print(f"long functions: {counts['long_function']}")
    print(f"engine attributes: {engine_attributes()}")
    print(f"design target: under 1500 root sloc (gap: {max(0, counts['sloc'] - 1499)} sloc)")
    print("10 worst root files:")
    print("\n".join(offenders()[:10]))


if __name__ == "__main__":
    main()
