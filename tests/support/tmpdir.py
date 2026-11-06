"""`TemporaryDirectory` and `mkdtemp` for tests, on contracts/scratch.py: the folder is under the scratch root (the checkout's disk),
never the system temp dir. Same names and use as the tempfile ones: `.name`, `.cleanup()`, a context manager yielding the path as a str."""
import os
import shutil
import weakref
from types import TracebackType

from taskloop.contracts import scratch


def mkdtemp(prefix: str | None = None) -> str:
    """A new empty scratch folder; the caller removes it."""
    return str(scratch.scratch_dir(os.environ, prefix or "wd-"))


class TemporaryDirectory:
    def __init__(self, prefix: str | None = None, ignore_cleanup_errors: bool = True) -> None:
        self.name = mkdtemp(prefix)
        self._finalizer = weakref.finalize(self, shutil.rmtree, self.name, True)

    def cleanup(self) -> None:
        self._finalizer()

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None, trace: TracebackType | None) -> None:
        self.cleanup()
