"""Append-only log files held open: one handle per path per process, every line written at once.

Open-append-close per record cost about 14 ms on a Mac whose antivirus scans each close (tl-64i); a kept-open handle costs
about 0.04 ms. The handle is unbuffered binary and each line goes out as one write() on an O_APPEND file: a reader tailing
the file sees the line when `append` returns, and two processes appending to one file never interleave inside a line.

- A handle belongs to the process that opened it: after a fork the child drops the inherited ones and opens its own.
- Handles are close-on-exec (PEP 446, set explicitly): a live-reload exec never carries one over; `close_all` before an
  exec closes them anyway.
- A path whose file was removed or replaced is opened afresh (one stat per append).
- At most MAX_OPEN handles are kept; the least recently used goes first.
Python 3.8+, stdlib only; imports nothing of the plugin.
"""
import atexit
import os
import threading

MAX_OPEN = 16

_lock = threading.RLock()
_open = {}  # str(path) -> (pid, file object), least recently used first


def _same(f, path):
    try:
        a, b = os.fstat(f.fileno()), os.stat(path)
    except (OSError, ValueError):
        return False
    return (a.st_ino, a.st_dev) == (b.st_ino, b.st_dev)


def _handle(path):
    key, pid = str(path), os.getpid()
    ent = _open.pop(key, None)
    if ent is not None and (ent[0] != pid or not _same(ent[1], key)):
        try:
            ent[1].close()  # an inherited fd closes only this process's copy
        except OSError:
            pass
        ent = None
    if ent is None:
        for k in [k for k, v in _open.items() if v[0] != pid]:  # inherited from the parent across a fork
            try:
                _open.pop(k)[1].close()
            except OSError:
                pass
        while len(_open) >= MAX_OPEN:
            try:
                _open.pop(next(iter(_open)))[1].close()
            except OSError:
                pass
        f = open(key, "ab", buffering=0)
        os.set_inheritable(f.fileno(), False)
        ent = (pid, f)
    _open[key] = ent
    return ent[1]


def append(path, text):
    """Write `text` (one or more whole lines) to `path` through the held handle. Raises OSError like open() would."""
    data = text.encode("utf-8", "surrogateescape")
    with _lock:
        f = _handle(path)
        try:
            f.write(data)
        except OSError:
            close(path)
            raise


def close(path):
    with _lock:
        ent = _open.pop(str(path), None)
        if ent is not None and ent[0] == os.getpid():
            try:
                ent[1].close()
            except OSError:
                pass


def close_all():
    with _lock:
        for key in list(_open):
            close(key)


def open_count(path=None):
    """Handles held by this process: for `path` 0 or 1, without it all."""
    with _lock:
        pid = os.getpid()
        return sum(1 for k, v in _open.items() if v[0] == pid and (path is None or k == str(path)))


atexit.register(close_all)
