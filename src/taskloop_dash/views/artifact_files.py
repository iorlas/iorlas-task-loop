"""What a registered file is, from its name alone: the kind it is served as, a store path part, a `<stage>-<attempt>` folder, one listed
item and the URL that reads it. Pure; the store reader is api/artifacts.py."""

from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import urlencode

from taskloop_dash.views import names

Kind = Literal["image", "video", "audio", "pdf", "file"]
Role = Literal["before", "after", "progress", "result"]
INLINE_VIDEO: Final = ("video/mp4", "video/webm", "video/ogg")
INLINE_AUDIO: Final = ("audio/mpeg", "audio/wav", "audio/x-wav", "audio/ogg", "audio/mp4", "audio/webm", "audio/aac", "audio/flac")
DOWNLOAD: Final = "application/octet-stream"


def served(name: str) -> tuple[Kind, str]:
    """(kind, content type) a file is served as: what plays inline is a fixed table of types (never HTML or SVG), the rest downloads."""
    ctype = names.content_type(name)
    if ctype in names.IMAGES:
        return "image", ctype
    if ctype in INLINE_VIDEO:
        return "video", ctype
    if ctype in INLINE_AUDIO:
        return "audio", ctype
    if ctype == "application/pdf":
        return "pdf", ctype
    return "file", DOWNLOAD


def plain(part: str) -> bool:
    """One path level of the store: not empty, no separator, not hidden (so never `.` or `..`)."""
    return bool(part) and "/" not in part and "\\" not in part and "\0" not in part and not part.startswith(".")


def split_stage(folder: str) -> tuple[str, int] | None:
    """`write-2` -> ("write", 2); None for a folder that is not `<stage>-<attempt>`."""
    stage, _, n = folder.rpartition("-")
    return (stage, int(n)) if stage and n.isascii() and n.isdigit() else None


@dataclass(frozen=True)
class Item:
    run: str
    stage: str
    attempt: int
    name: str
    kind: Kind
    caption: str
    role: Role
    t: float


def url_of(repo: str, bead: str, i: Item) -> str:
    return "/api/artifact?" + urlencode({"repo": repo, "bead": bead, "run": i.run, "stage": i.stage, "attempt": i.attempt, "name": i.name})
