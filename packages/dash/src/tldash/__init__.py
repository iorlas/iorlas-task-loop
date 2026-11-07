"""The task-loop dashboard: its own process, read-only, importing tlkernel and nothing else of the engine."""
from importlib.util import find_spec

if find_spec("tlpaths") is not None:
    import tlpaths  # noqa: F401  (checkout workspace bootstrap)
