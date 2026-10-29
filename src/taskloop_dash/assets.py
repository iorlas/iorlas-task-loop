"""Read-only static files for the v2 page: .js/.css/.html under the static dir, never outside it."""

from pathlib import Path
from types import MappingProxyType
from typing import Final
from urllib.parse import unquote

TYPES: Final = MappingProxyType(
    {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".html": "text/html; charset=utf-8"}
)
DENY = frozenset({"components.html", "components.js"})  # dev-only
MAX_BYTES = 2_000_000
NOT_FOUND = (404, b"not found", "text/plain")


def static_file(static: Path, path: str) -> tuple[int, bytes, str]:
    """(200, bytes, type) of `path` when it is a servable file inside `static`, else a bare 404."""
    rel = unquote(path)
    if path.startswith("/v2") and rel in ("/v2", "/v2.html"):
        rel = "/v2.html"
    if not rel.startswith("/") or "\0" in rel or "\\" in rel or rel.startswith("//"):
        return NOT_FOUND
    parts = rel[1:].split("/")
    if any(p in ("", ".", "..") or p.startswith(".") for p in parts) or parts[-1] in DENY:
        return NOT_FOUND
    ctype = TYPES.get(Path(parts[-1]).suffix)
    if ctype is None:
        return NOT_FOUND
    try:
        root = static.resolve()
        real = root.joinpath(*parts).resolve()
        if not real.is_relative_to(root) or not real.is_file() or real.stat().st_size > MAX_BYTES:
            return NOT_FOUND
        return 200, real.read_bytes(), ctype
    except (OSError, ValueError):
        return NOT_FOUND
