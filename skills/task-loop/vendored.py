"""Put skills/task-loop/_vendor on sys.path, once. Every consumer of a vendored shelf package imports this first:

    import vendored  # noqa: F401
    from git_porcelain import RealRepo
    from atomic_io import atomic_write_json

The vendored packages (dev/vendor.py) keep their absolute imports, so their top-level names (git_porcelain, atomic_io, jsonl_log, process_lock) must resolve.
Nothing else adds a path for them. Stdlib only.
"""
import sys
from pathlib import Path

VENDOR_DIR = str(Path(__file__).resolve().parent / "_vendor")

if VENDOR_DIR not in sys.path:
    sys.path.append(VENDOR_DIR)
