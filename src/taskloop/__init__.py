"""task-loop engine package (the rewrite grows here one slice per release; see docs/design).

Importing it puts the vendored shelf packages (skills/task-loop/_vendor, dev/vendor.py) on sys.path: they keep their absolute
imports (git_porcelain, atomic_io, jsonl_log, process_lock, stream_proc, child_env), so their top-level names must resolve.
Every entry point (tl.py, hooks/hook.py, dev/*.py) puts `src/` on the path and nothing else."""
import sys
from pathlib import Path

_VENDOR = str(Path(__file__).resolve().parents[2] / "skills" / "task-loop" / "_vendor")
if _VENDOR not in sys.path:
    sys.path.append(_VENDOR)
