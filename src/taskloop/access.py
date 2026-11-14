"""What the agent's sandbox may touch: the Codex access values of every step kind, the folders an implement agent writes
outside its slot, and the environment that points its tools at them (S5e, design tl-8bh9.4.3.1.16.2 sections 3 and 5).
A leaf: values and pure functions only; nothing here runs, reads or writes."""

import enum
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from any_agent.access import CodexAccess, CodexApproval, CodexSandbox


class Sandbox(enum.StrEnum):
    """The agent's sandbox, the machine config's `agent_sandbox`. It is stored on the attempt as its value."""

    WORKSPACE_WRITE = "workspace-write"
    DANGER_FULL_ACCESS = "danger-full-access"  # no sandbox: the machine's own boundary (a container) is the only one


SANDBOX: Final = Sandbox.WORKSPACE_WRITE.value  # the default, and the only mode CODEX_ACCESS constrains; both step kinds
ROOTS: Final = "sandbox_workspace_write.writable_roots="
SHELL: Final = "shell_environment_policy.set."  # a variable for the agent's shell commands only, not Codex's own process
# Neither the user's config nor a repo file widens or narrows these. The sandbox has no network; it writes the working
# directory and, by Codex's default, also /tmp and $TMPDIR, which the two `exclude_*` keys remove (so the agent cannot
# stage a Git directory there). A command it blocks fails back to the model (`never`: no escalation, so no reviewer).
# The agent never writes Git: the factory commits the paths it lists (tl-8bh9.4.3.1.7). Keys and values read from codex
# 0.167.0's strings (its SandboxWorkspaceWrite fields). The plan step's access, byte for byte.
CODEX_ACCESS: Final = (
    "--ignore-user-config",
    "--ignore-rules",
    "-c",
    "sandbox_workspace_write.network_access=false",
    "-c",
    ROOTS + "[]",
    "-c",
    "sandbox_workspace_write.exclude_slash_tmp=true",
    "-c",
    "sandbox_workspace_write.exclude_tmpdir_env_var=true",
    "-c",
    "approval_policy=never",
    "-c",
    "tool_output_token_limit=3000",
)
# `codex sandbox` (0.167.0) takes neither flag and no `-s`: the mode is a config key there.
EXEC_ONLY: Final = ("--ignore-user-config", "--ignore-rules")
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


def prepared_access(found: Folders) -> tuple[str, ...]:
    """CODEX_ACCESS with the three folders as writable roots (a JSON array of strings, which is a valid TOML array), then
    `agent_env` as `shell_environment_policy.set` keys: only the agent's shell gets them, so Codex's own process keeps
    the person's TMPDIR (outside every root). Network stays off and both `exclude_*` keys stay: `TMPDIR`, itself a root,
    stays writable (Run S finding 2b). Codex's sandbox launcher still keeps its mount registry
    (`codex-bwrap-synthetic-mount-targets-<uid>`) in the shell's TMPDIR, as it does in `/tmp` by default (plan section 19)."""
    roots = ROOTS + json.dumps([str(path) for path in found.roots])
    shell = [part for name, value in agent_env(found).items() for part in ("-c", f"{SHELL}{name}={json.dumps(value)}")]
    return (*(roots if item == ROOTS + "[]" else item for item in CODEX_ACCESS), *shell)


# Checks the shell got TMPDIR (the first root) and UV_OFFLINE (exit 5), creates and removes a folder of an unpredictable
# name in each root (exit 3 when it cannot; no `rm`), then fails when it can create one in /tmp (exit 4).
PROBE: Final = (
    '[ "$TMPDIR" = "$1" ] && [ "$UV_OFFLINE" = 1 ] || exit 5; '
    'for d in "$@"; do t=$(mktemp -d "$d/.tl-probe-XXXXXX") && rmdir "$t" || exit 3; done; '
    'if t=$(mktemp -d /tmp/.tl-probe-XXXXXX 2>/dev/null); then rmdir "$t"; exit 4; fi'
)


def probe_argv(exe: str, found: Folders) -> list[str]:
    """`codex sandbox` running PROBE under the implement agent's sandbox: the mode as a key, then every `-c` key of
    `prepared_access`, the shell's variables included (the agent's `exec` flags are not accepted there, so the person's
    Codex config is read beneath these keys)."""
    keys = [item for item in prepared_access(found) if item not in EXEC_ONLY]
    return [exe, "sandbox", "-c", f'sandbox_mode="{SANDBOX}"', *keys, "--", "/bin/sh", "-c", PROBE, "sh",
            *(str(path) for path in found.roots)]


def full_access(found: Folders | None) -> CodexAccess:
    """The `danger-full-access` mode: CODEX_ACCESS's choices that are not about the sandbox (never ask, the person's config
    and rules ignored, the output limit) and, for a kind with `environment` (`found`), the shell's variables of `agent_env`.
    No root, network or temp-folder key: they belong to the workspace-write mode, and nothing asks for bwrap."""
    shell = () if found is None else tuple(agent_env(found).items())
    return CodexAccess(sandbox=CodexSandbox.DANGER_FULL_ACCESS, approval=CodexApproval.NEVER, tool_output_token_limit=3000,
                       ignore_user_config=True, ignore_rules=True, shell_env=shell)
