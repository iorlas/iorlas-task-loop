"""One primitive, replaced where every module bound it: `from x import f` copies the name, so patching `x.f` alone reaches nobody.
For the race harness, where threads run the real lock, lease and claim code against a fake clock, process table and actor."""
import sys
from unittest import mock


def rebind(test, original, replacement):
    """Every module-level name that is `original` becomes `replacement` until the test's cleanup."""
    for mod in list(sys.modules.values()):
        for name, val in list(getattr(mod, "__dict__", {}).items()):
            if val is original:
                p = mock.patch.object(mod, name, replacement)
                p.start()
                test.addCleanup(p.stop)
