"""The artifact_add tool as a stdio MCP server (JSON-RPC lines), one child per worker call. The binding (store, slot, working folder)
comes from the caller's argv, never from the model. The child runs outside every harness sandbox, so rules.py and the writer are the
only guard; a refusal goes back to the model as an error result it can act on."""
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Final, TextIO

from taskloop.app.artifacts import rules, store
from taskloop.contracts.artifact import CAPTION_MAX, ROLES, ArtifactSlot
from taskloop.contracts.wire import Refused

PROTOCOL: Final = "2025-06-18"
type Obj = dict[str, object]
FIELDS: Final = ("path", "caption", "role", "name")
TOOL: Final[Obj] = {
    "name": "artifact_add",
    "description": (
        "Register a picture, PDF, video or audio file you made as an artifact of this step; it is copied into the factory's store and "
        "shown on the bead's page. The file must be inside your working folder. Register progress pictures even when the task does not "
        "ask for any. When the change touches what the user sees, register a picture with role 'before' before you start and one with "
        "role 'after' when you are done."),
    "inputSchema": {
        "type": "object", "required": list(FIELDS), "additionalProperties": False,
        "properties": {
            "path": {"type": "string", "description": "Path of the file, relative to your working folder"},
            "caption": {"type": "string", "description": f"What it shows, up to {CAPTION_MAX} characters"},
            "role": {"type": "string", "enum": list(ROLES), "description": "before/after a change, progress, or the final result"},
            "name": {"type": "string", "description": "Plain file name for the store, no folders, e.g. home.png"},
        },
    },
}


def call(root: Path, slot: ArtifactSlot, cwd: Path, args: Obj, now: float) -> str:
    """The tool's text for one call; raises Refused."""
    given = {k: args.get(k) for k in FIELDS}
    for k, v in given.items():
        if not isinstance(v, str) or not v:
            raise Refused(f"{k} is required and must be a non-empty string")
    path, caption, role, name = (str(given[k]) for k in FIELDS)
    meta = store.add(root, slot, rules.source(cwd, path), name=name, caption=caption, role=role, now=now)
    return f"registered {meta.name} ({meta.kind}, {meta.size} bytes, role {meta.role}) as an artifact of {slot.stage} {slot.attempt}"


def answer(root: Path, slot: ArtifactSlot, cwd: Path, msg: Obj, now: Callable[[], float]) -> Obj | None:
    """The JSON-RPC reply to one message, None when it wants none (a notification)."""
    method, i = msg.get("method"), msg.get("id")
    raw = msg.get("params")
    params: Obj = raw if isinstance(raw, dict) else {}
    if method == "initialize":
        result: Obj = {"protocolVersion": params.get("protocolVersion", PROTOCOL), "capabilities": {"tools": {}},
                       "serverInfo": {"name": "task-loop-artifacts", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        if params.get("name") != "artifact_add":
            return {"jsonrpc": "2.0", "id": i, "error": {"code": -32602, "message": "unknown tool"}}
        try:
            given = params.get("arguments")
            text, bad = call(root, slot, cwd, given if isinstance(given, dict) else {}, now()), False
        except (Refused, OSError) as e:  # a tool error goes back to the model, never into the harness
            text, bad = f"artifact_add refused: {e}", True
        result = {"content": [{"type": "text", "text": text}], "isError": bad}
    elif i is not None:
        result = {}
    else:
        return None
    return {"jsonrpc": "2.0", "id": i, "result": result}


def serve(lines: Iterable[str], out: TextIO, root: Path, slot: ArtifactSlot, cwd: Path, now: Callable[[], float]) -> int:
    for line in lines:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        reply = answer(root, slot, cwd, msg, now)
        if reply is not None:
            out.write(json.dumps(reply) + "\n")
            out.flush()
    return 0
