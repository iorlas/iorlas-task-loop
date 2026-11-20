"""The slot environment's real ports (S5e, design tl-8bh9.4.3.1.16.2): one setup command through the shelf's registered
start, the environment folders on the real file system, and the probe of the implement agent's sandbox through
`codex sandbox`. Wired by `composition`; the entry and the slot release reach them through their ports."""

import os
import shutil
import stat
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from stream_proc import OwnedProcess, RegisteredStartUncertainError, capture, run_registered

from taskloop.access import Folders, folders
from taskloop.environment import SetupEnded

PROBE_SECONDS: Final = 30.0


def setup_process(
    argv: Sequence[str], *, registered: Callable[[OwnedProcess], None], cwd: str, env: Mapping[str, str], timeout: float,
    line: Callable[[bytes], None],
) -> SetupEnded:
    """One setup command through the shelf's registered start (its identity committed before it executes; stdin empty,
    stderr merged; the deadline stops and proves its tree). An uncertain start is not waited for."""
    try:
        done = run_registered(argv, registered=registered, cwd=cwd, env=env, timeout=timeout, on_line=line)
    except RegisteredStartUncertainError as error:
        return SetupEnded(None, False, False, error.identity.pgid, uncertain=True)
    return SetupEnded(done.returncode, done.timed_out is not None, done.exec_errno is not None, done.pgid,
                      survivors=bool(done.survivors))


REMOVERS = (os.unlink, os.rmdir)  # an entry's own removal: a PermissionError there is its parent's mode


class _Writable:
    """`rmtree`'s `onexc` for what an agent can do in its roots: a directory made unreadable (a PermissionError opening or
    listing a path `lstat` shows to be a directory, not a link) gets owner `rwx` and is removed again; an entry its
    parent forbids removing (unlink or rmdir) gets owner `rwx` on that parent and is removed again. Each path is retried
    once; a vanished path is done; anything else stays and the removal fails."""

    def __init__(self) -> None:
        self.tried: set[str] = set()

    def __call__(self, function: Callable[..., object], path: str, error: BaseException) -> None:
        if not isinstance(error, PermissionError) or path in self.tried:
            raise error
        self.tried.add(path)
        target = os.path.dirname(path) if function in REMOVERS else path
        try:
            found = os.lstat(target)
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(found.st_mode):
            raise error
        os.chmod(target, stat.S_IMODE(found.st_mode) | stat.S_IRWXU)
        if function in REMOVERS:
            function(path)
        else:
            shutil.rmtree(path, onexc=self)


def _remove(path: str, retry: _Writable) -> None:
    """One entry of an emptied folder: a directory through the symlink-safe `rmtree`, anything else (a link included)
    unlinked; a PermissionError of the unlink goes through `retry` as `rmtree`'s own would."""
    if stat.S_ISDIR(os.lstat(path).st_mode):
        shutil.rmtree(path, onexc=retry)
        return
    try:
        os.unlink(path)
    except PermissionError as error:
        retry(os.unlink, path, error)


class RealEnvFiles:
    """The environment folders on the real file system: created 0700, emptied with the symlink-safe `rmtree` only
    (`avoids_symlink_attacks`, checked by the preflight); a link is unlinked, never followed."""

    def resolve(self, path: Path) -> Path | None:
        try:
            return path.resolve()
        except (OSError, RuntimeError, ValueError):
            return None

    def ensure(self, path: Path) -> bool:
        """Made 0700 when missing; an existing one gets 0700 again through a descriptor opened without following a link
        (an agent may have made its root read-only)."""
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError:
            return False
        try:
            os.fchmod(descriptor, 0o700)
        except OSError:
            return False
        finally:
            os.close(descriptor)
        return True

    def empty_scratch(self, slot: Path) -> bool:
        """The slot release's emptying of `.t/<slot>`, only while it resolves exactly beside the resolved slot (no link
        on the way); otherwise nothing is touched."""
        tmp, base = folders(slot).tmp, self.resolve(slot.parent)
        if base is None or self.resolve(tmp) != folders(base / slot.name).tmp:
            return False
        return self.empty(tmp)

    def empty(self, path: Path) -> bool:
        """Every entry is tried; an entry that vanished meanwhile is removed. False when anything stays."""
        try:
            if not stat.S_ISDIR(os.lstat(path).st_mode):
                return False
            with os.scandir(path) as listing:
                names = [entry.path for entry in listing]
        except FileNotFoundError:
            return True
        except OSError:
            return False
        retry, emptied = _Writable(), True
        for name in names:
            try:
                _remove(name, retry)
            except FileNotFoundError:
                continue
            except OSError:
                emptied = False
        return emptied


def sandbox_probe(argv: Sequence[str], env: Mapping[str, str], found: Folders) -> bool:
    """Whether the implement agent's sandbox works on this machine: `codex sandbox` with the agent's keys and environment,
    run in the just emptied scratch (never the slot: a Codex shim there could read the slot's not yet reset files), gives
    the shell its variables, writes each folder and not /tmp (`access.PROBE`): exit 0 within PROBE_SECONDS through the
    shelf's capture (an external-tool reason: only Codex knows its backend, bubblewrap on Linux). The probe removes its own
    folders; a start failure or a process left behind is a failed probe."""
    try:
        done = capture(argv, cwd=found.tmp, env=env, timeout=PROBE_SECONDS)
    except OSError:
        return False
    return done.exit == 0 and not done.timed_out and not done.survivors
