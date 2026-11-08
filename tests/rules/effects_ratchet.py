"""Kernel effects judged against the merge base, with no stored baseline.

Kinds: sqlite (sqlite3 imports), process (stream_proc/subprocess/signal imports), files
(shutil/tempfile/fcntl imports and named filesystem calls), net (socket/urllib/http imports),
and threads (threading imports). Each imported module is one site; dotted imports use
its root module. Calls named open, write_text, read_text, write_bytes, read_bytes, unlink,
mkdir, rmdir, rmtree, rename, touch and fsync count, as do os.replace and os.remove.
Only os.replace counts as replace: str.replace is noise. This is syntactic: even a
module's locally defined open( counts; aliases and shadowing are not resolved.
Testing helpers under testing/ are excluded. Only touched .py files are compared;
new files start at zero and moves are net zero. Diagnostics use `<kind>: +N`.
A deliberate rise requires a commit line `Ratchet-allow: effects +N <reason in words>`
with at least four words in the reason (ratchet_change.py).
"""
import ast
from collections import Counter
from pathlib import Path

KERNEL = Path("packages/kernel/src/tlkernel")
IMPORT_KINDS = {
    "sqlite3": "sqlite",
    "stream_proc": "process", "subprocess": "process", "signal": "process",
    "shutil": "files", "tempfile": "files", "fcntl": "files",
    "socket": "net", "urllib": "net", "http": "net",
    "threading": "threads",
}
FILE_CALLS = frozenset({"open", "write_text", "read_text", "write_bytes", "read_bytes",
                        "unlink", "mkdir", "rmdir", "rmtree", "rename", "touch", "fsync"})


def file_call(fn: ast.expr) -> bool:
    """Named filesystem operations, with replace/remove restricted to the os receiver."""
    if isinstance(fn, ast.Name):
        return fn.id in FILE_CALLS
    if isinstance(fn, ast.Attribute):
        return fn.attr in FILE_CALLS or (
            fn.attr in {"replace", "remove"} and isinstance(fn.value, ast.Name) and fn.value.id == "os")
    return False


def file_counts(rel: str, tree: ast.Module) -> dict[str, int]:
    """Count effect sites by kind in one kernel source file; other paths are empty."""
    path = Path(rel)
    if not path.is_relative_to(KERNEL) or path.suffix != ".py" or "testing" in path.relative_to(KERNEL).parts:
        return {}
    found: Counter[str] = Counter()
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            modules = [node.module]
        for module in modules:
            kind = IMPORT_KINDS.get(module.split(".")[0])
            if kind:
                found[kind] += 1
        if isinstance(node, ast.Call) and file_call(node.func):
            found["files"] += 1
    return dict(found)
