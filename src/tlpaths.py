"""tlpaths: put every workspace package's src/ on sys.path. Stdlib only, idempotent. The plugin runs from a checkout with `src/` on the path
and nothing else (no installed packages), so each entry point imports this once, and `taskloop` and `tldash` import it first."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _src in sorted((ROOT / "packages").glob("*/src")):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
