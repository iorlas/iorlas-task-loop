"""`python3 -m taskloop_dash`: start the dash. The flat engine code is not imported here: `--ports MODULE:FUNC` names a callable that
returns the `Ports` (the launcher, tl.py, supplies one), resolved by the injected `load`; with no `--ports` the dash serves its own files
and says nothing for the facts only the engine holds."""

import argparse
import hashlib
import importlib
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType

from taskloop.contracts import env as penv
from taskloop.contracts.paths import default_root
from taskloop_dash import serve
from taskloop_dash.env import Env, Ports

PACKAGE = Path(__file__).resolve().parents[1]
SKIP_DIRS = frozenset({"__pycache__"})


def code_version(package: Path = PACKAGE) -> str:
    """A short hash of every file of the package: a running dash from older code is replaced."""
    h = hashlib.sha256()
    for p in sorted(package.rglob("*")):
        if p.is_file() and not SKIP_DIRS.intersection(p.parts):
            h.update(p.relative_to(package).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def resolve_ports(spec: str | None, env: penv.Env, load: Callable[[str], ModuleType] = importlib.import_module) -> Ports:
    """`module:func` -> the Ports that function returns; no spec -> Ports() that say nothing."""
    if not spec:
        return Ports()
    module, _, func = spec.partition(":")
    return getattr(load(module), func or "ports")(env)


def main(argv: Sequence[str] | None = None, load: Callable[[str], ModuleType] = importlib.import_module,
         here: Path = PACKAGE) -> None:
    ap = argparse.ArgumentParser(prog="python3 -m taskloop_dash", add_help=False, allow_abbrev=False)
    ap.add_argument("--ports", default=None, help="MODULE:FUNC returning the Ports (the engine's read-only facts)")
    known, rest = ap.parse_known_args(argv)
    process = penv.snapshot()
    env = Env(config=default_root(process), ports=resolve_ports(known.ports, process, load), version=code_version())
    serve.main(env, here, process, rest)  # the dash's edge: the process environment is taken here, once
