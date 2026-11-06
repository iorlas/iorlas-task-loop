"""The lease table a fake keeps in a temp folder (the lock table itself is adapters/locks.py)."""
import shutil
import tempfile
import weakref
from pathlib import Path

from any_lease import Leases


def temp_leases() -> Leases:
    """A lease table of its own in a temp folder, for fakes (flocks are the real thing: one folder is one table); removed with the table."""
    root = tempfile.mkdtemp(prefix="tl-leases-")
    table = Leases(Path(root))
    weakref.finalize(table, shutil.rmtree, root, True)
    return table
