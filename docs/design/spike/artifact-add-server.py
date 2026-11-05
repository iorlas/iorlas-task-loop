"""Throwaway spike: stdio MCP server exposing artifact_add. Binding comes from argv, never from the model."""
import argparse, datetime, hashlib, json, os, re, shutil, sys

ROLES = ("shot", "scene", "page", "pdf", "video", "audio", "other")
CAP = 200
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,99}$")
MAGIC = [(b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF8", "gif"), (b"%PDF-", "pdf"),
         (b"RIFF", "riff"), (b"\x1aE\xdf\xa3", "webm"), (b"OggS", "ogg"), (b"ID3", "mp3")]

ap = argparse.ArgumentParser()
for k in ("bead", "run", "stage", "attempt", "store", "cwd"):
    ap.add_argument("--" + k, required=True)
A = ap.parse_args()

TOOL = {"name": "artifact_add",
        "description": "Register a file you made (picture, PDF, video) as an artifact of this step. The file must be inside your working folder.",
        "inputSchema": {"type": "object", "required": ["path", "caption", "role", "name"], "properties": {
            "path": {"type": "string", "description": "Path of the file inside the working folder"},
            "caption": {"type": "string", "description": f"What it shows, up to {CAP} characters"},
            "role": {"type": "string", "enum": list(ROLES)},
            "name": {"type": "string", "description": "Plain file name for the store, no folders, e.g. home.png"}}}}


def sniff(head):
    for m, k in MAGIC:
        if head.startswith(m):
            return k
    return None


def add(a):
    for k in ("path", "caption", "role", "name"):
        if not isinstance(a.get(k), str) or not a[k]:
            raise ValueError(f"{k} is required and must be a non-empty string")
    if a["role"] not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    if len(a["caption"]) > CAP:
        raise ValueError(f"caption is {len(a['caption'])} characters; the limit is {CAP}")
    n = a["name"]
    if "/" in n or "\\" in n or ".." in n or os.path.isabs(n) or not NAME.match(n):
        raise ValueError("name must be a plain file name (letters, digits, . _ - space); no folders, '..' or absolute path")
    cwd = os.path.realpath(A.cwd)
    p = a["path"] if os.path.isabs(a["path"]) else os.path.join(cwd, a["path"])
    if os.path.islink(p) or any(os.path.islink(x) for x in _parents(p, cwd)):
        raise ValueError("path is or passes through a symlink; symlinks are refused")
    rp = os.path.realpath(p)
    if os.path.commonpath([rp, cwd]) != cwd:
        raise ValueError(f"path is outside the working folder {cwd}")
    if not os.path.isfile(rp):
        raise ValueError(f"no such file: {a['path']}")
    with open(rp, "rb") as f:
        head = f.read(16)
    kind = sniff(head)
    if not kind:
        raise ValueError("unsupported file type (magic bytes match none of png, jpg, gif, pdf, webm, mp3, ogg)")
    d = os.path.join(A.store, A.bead, A.run, A.stage, A.attempt)
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, n)
    tmp = dest + ".tmp"
    shutil.copyfile(rp, tmp)
    os.replace(tmp, dest)                                    # file first
    h = hashlib.sha256(open(dest, "rb").read()).hexdigest()
    side = {"bead": A.bead, "run": A.run, "stage": A.stage, "attempt": A.attempt, "name": n, "role": a["role"],
            "caption": a["caption"], "kind": kind, "size": os.path.getsize(dest), "sha256": h,
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    stmp = dest + ".json.tmp"
    open(stmp, "w").write(json.dumps(side))
    os.replace(stmp, dest + ".json")                         # sidecar last
    return f"registered {n} ({kind}, {side['size']} bytes) as artifact {A.bead}/{A.run}/{A.stage}/{A.attempt}/{n}"


def _parents(p, cwd):
    x = os.path.dirname(p)
    while len(x) > len(cwd) and x.startswith(cwd):
        yield x
        x = os.path.dirname(x)


def reply(i, **kw):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": i, **kw}) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    try:
        m = json.loads(line)
    except ValueError:
        continue
    meth, i = m.get("method"), m.get("id")
    if meth == "initialize":
        reply(i, result={"protocolVersion": m["params"].get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}},
                         "serverInfo": {"name": "spike-artifacts", "version": "0"}})
    elif meth == "tools/list":
        reply(i, result={"tools": [TOOL]})
    elif meth == "tools/call":
        p = m["params"]
        if p.get("name") != "artifact_add":
            reply(i, error={"code": -32602, "message": "unknown tool"})
            continue
        try:
            out = add(p.get("arguments") or {})
            reply(i, result={"content": [{"type": "text", "text": out}]})
        except Exception as e:                            # tool error goes back to the model
            reply(i, result={"isError": True, "content": [{"type": "text", "text": f"artifact_add refused: {e}"}]})
    elif i is not None:
        reply(i, result={})
