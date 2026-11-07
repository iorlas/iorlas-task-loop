"""pass_files: the files a check is handed as trailing argv (the pre-commit model), and the skip when none match."""
from collections.abc import Sequence

from tlkernel.checks import Check

from taskloop.domain.checks.inputs import matching


def files_for(c: Check, changed: Sequence[str], tracked: Sequence[str] | None) -> list[str]:
    """The paths a pass_files check receives: `tracked` (every tracked file) when given, else `changed`, kept to its `when` globs
    (none named: all of them). A path that could read as an option is written `./path`."""
    paths = [p for p in (tracked if tracked is not None else changed) if p]
    found = matching(paths, c.when) if c.when else paths
    return [p if not p.startswith("-") else "./" + p for p in found]


def none_why(c: Check, everything: bool) -> str:
    """Why a pass_files check with no file to read does not run."""
    scope = "tracked file" if everything else "changed file"
    return f"no {scope} under {', '.join(c.when)}" if c.when else f"no {scope}"
