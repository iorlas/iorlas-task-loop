"""The folders an implement agent writes outside its slot and the shell environment that points tools at them
(S5e, design tl-8bh9.4.3.1.16.2 sections 3 and 5).
A leaf: values and pure functions only; nothing here runs, reads or writes."""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

SANDBOX: Final = "workspace-write"  # the default mode; vendor policy translation lives in agents.launch
TMP_BYTES: Final = 64  # TMPDIR's budget: a Unix socket path holds 107 bytes on Linux, so a test may append 43


@dataclass(frozen=True)
class Folders:
    """Beside the slots and `.locks/` under `<slots_root>/<repo name>/`: the scratch (`TMPDIR`), uv's cache and its tools.
    The factory creates each before launch: Codex silently drops a writable root that does not exist."""

    tmp: Path
    cache: Path
    tools: Path

    @property
    def env(self) -> Path:
        """`.env/<slot>`: emptied whole by every reset."""
        return self.cache.parent

    @property
    def roots(self) -> tuple[Path, Path, Path]:
        return self.tmp, self.cache, self.tools


def folders(slot: Path) -> Folders:
    return Folders(slot.parent / ".t" / slot.name, slot.parent / ".env" / slot.name / "uv-cache",
                   slot.parent / ".env" / slot.name / "uv-tools")


def agent_env(found: Folders) -> dict[str, str]:
    """What the implement agent's shell gets beyond its inherited environment: its temporary files, uv's cache and tools
    in the roots, and uv offline (setup filled the cache). No name contains KEY, SECRET or TOKEN, which Codex's default
    `shell_environment_policy` drops."""
    return {"TMPDIR": str(found.tmp), "UV_CACHE_DIR": str(found.cache), "UV_TOOL_DIR": str(found.tools), "UV_OFFLINE": "1"}



# Checks the shell got TMPDIR (the first root) and UV_OFFLINE (exit 5), creates and removes a folder of an unpredictable
# name in each root (exit 3 when it cannot; no `rm`), then fails when it can create one in /tmp (exit 4).
PROBE: Final = (
    '[ "$TMPDIR" = "$1" ] && [ "$UV_OFFLINE" = 1 ] || exit 5; '
    'for d in "$@"; do t=$(mktemp -d "$d/.tl-probe-XXXXXX") && rmdir "$t" || exit 3; done; '
    'if t=$(mktemp -d /tmp/.tl-probe-XXXXXX 2>/dev/null); then rmdir "$t"; exit 4; fi'
)
