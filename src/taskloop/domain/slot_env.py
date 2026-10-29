"""The environment of one slot: what every command a bead runs in that slot is given, so no two slots share a temp file, a pipe or
a lock (the .NET compiler server, MSBuild nodes, NuGet scratch). Pure: the caller makes the folders."""
from collections.abc import Mapping
from pathlib import Path

from taskloop.contracts.config import fill_slot_env


def repo_id(origin: str, fallback: str) -> str:
    """A short name of the repo for ids and folders: the origin url's last part (else the folder's), made of [\\w.-]."""
    name = Path((origin or fallback).rstrip("/")).name
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name.removesuffix(".git"))[:40] or "repo"


def slot_env(state: Path, repo: str, slot: str, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """TMPDIR/TMP/TEMP, DOTNET_CLI_HOME and the NuGet scratch and caches under `state` (the slot's folder outside its worktree), the
    compiler-server and MSBuild-node ids `<repo>-<slot>`, and TL_SLOT; then `extra` (engine.slot_env) over them, placeholders filled."""
    tmp, nuget, ident = str(state / "tmp"), state / "nuget", f"{repo}-{slot}"
    base = {"TMPDIR": tmp, "TMP": tmp, "TEMP": tmp, "DOTNET_CLI_HOME": str(state / "dotnet"),
            "NUGET_SCRATCH": str(nuget / "scratch"), "NUGET_HTTP_CACHE_PATH": str(nuget / "http-cache"),
            "NUGET_PLUGINS_CACHE_PATH": str(nuget / "plugins-cache"), "SharedCompilationId": ident,
            "MSBUILDNODEHANDSHAKESALT": ident, "TL_SLOT": slot}
    return {**base, **fill_slot_env(extra or {}, slot=slot, slot_dir=str(state), repo=repo)}


def folders(env: Mapping[str, str]) -> list[str]:
    """The folders the base environment names (made on use): every value that is a path under the slot's state."""
    keys = ("TMPDIR", "DOTNET_CLI_HOME", "NUGET_SCRATCH", "NUGET_HTTP_CACHE_PATH", "NUGET_PLUGINS_CACHE_PATH")
    return [env[k] for k in keys if k in env]
