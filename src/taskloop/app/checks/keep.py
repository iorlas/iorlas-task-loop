"""Keep: after each attempt of a check, its log and the files its `keep` globs name (a Unity log, a result XML) are copied, never
linked, into <run folder>/artifacts/<check>/attempt-N/. The next attempt, the next run in the slot and the slot's reset all overwrite
the originals; the copy is a new directory per attempt, written once (read-only), with one Evidence row per file (sha256 and bytes).
Nothing here raises into the engine: evidence is never worth a run."""
import hashlib
from pathlib import Path

from taskloop.app.checks.host import CheckHost
from taskloop.contracts.checks import Check
from taskloop.contracts.log import Evidence
from taskloop.domain.checks.matchers import safe_name

LOG_NAME = "check.log"
MAX_BYTES = 512 * 1024 * 1024


def attempt_dir(root: Path) -> Path:
    """The next attempt-N directory under `root`, made now: an earlier attempt's directory is never reused."""
    root.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        d = root / f"attempt-{n}"
        try:
            d.mkdir()
            return d
        except FileExistsError:
            n += 1


def files_of(c: Check, wt: Path, log: Path) -> list[tuple[Path, str]]:
    """(source, name in the attempt directory): the check's log, then every regular file under the tree that a `keep` glob names."""
    found: list[tuple[Path, str]] = [(log, LOG_NAME)] if log.is_file() else []
    top = wt.resolve()
    for pat in c.keep:
        for p in sorted(wt.glob(pat)):
            if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(top) and p.stat().st_size <= MAX_BYTES:
                found.append((p, p.relative_to(wt).as_posix()))
    return found


def copy_once(src: Path, dst: Path) -> tuple[str, int]:
    """Copy `src` to the new file `dst` (it must not exist), read-only after. -> (sha256 of what was copied, its bytes)."""
    h, n = hashlib.sha256(), 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, "rb") as i, open(dst, "xb") as o:
        while chunk := i.read(1 << 20):
            h.update(chunk)
            n += len(chunk)
            o.write(chunk)
    dst.chmod(0o444)
    return h.hexdigest(), n


def keep(host: CheckHost, c: Check, log: Path) -> None:
    """Copy the evidence of the attempt that just ended and say so, one row per file."""
    try:
        files = files_of(c, Path(host.wt), log)
        if not files:
            return
        base = host.run_dir / "artifacts" / safe_name(c.id)
        d = attempt_dir(base)
        n = int(d.name.removeprefix("attempt-"))
        for src, name in files:
            digest, size = copy_once(src, d / name)
            host.log.emit(Evidence(call_id=c.id, attempt=n, bytes=size, artifact=(d / name).relative_to(host.run_dir).as_posix(),
                                   artifact_hash=digest))
    except (OSError, ValueError, NotImplementedError) as e:
        host.warn(f"evidence of `{c.id}` not kept: {type(e).__name__}: {e}")
