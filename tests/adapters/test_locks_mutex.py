"""adapters/locks.hold_path: an error from ProcessLock.acquire other than LockHeldError gives the in-process mutex back."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.tags import domain

from taskloop.adapters import locks
from taskloop.adapters.locks import ProcessLock, hold_path


@domain
class MutexReleased(unittest.TestCase):
    def test_an_oserror_from_acquire_does_not_leave_the_path_locked_for_the_next_holder(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.lock"
            real, calls = ProcessLock.acquire, []

            def acquire(p: Path) -> ProcessLock:
                calls.append(p)
                if len(calls) == 1:
                    raise OSError("disk")
                return real(p)
            with mock.patch.object(locks.ProcessLock, "acquire", side_effect=acquire), self.assertRaises(OSError), \
                    hold_path(path, "a", timeout=1):
                pass
            with hold_path(path, "b", timeout=1) as rec:  # waits forever (here: LockTimeout) when the mutex stayed taken
                self.assertEqual(rec.holder, "b")


if __name__ == "__main__":
    unittest.main()
