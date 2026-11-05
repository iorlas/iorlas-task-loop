"""What may become an artifact: the checks the writer and the tool server share. Plain string and byte tests; no pattern matching.
A refusal raises Refused with a message the model can act on."""
import fnmatch
import os
from pathlib import Path
from typing import Final

from taskloop.contracts.artifact import CAPTION_MAX, ROLES, Kind, Role
from taskloop.contracts.wire import Refused

SECRET_NAMES: Final = (".env*", "*.pem", "*.key", "id_*", "*token*", "*secret*")
MAX_BYTES: Final = 25 * 1024 * 1024
NAME_MAX: Final = 100
NAME_CHARS: Final = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- ")
SUFFIX_KIND: Final[dict[str, Kind]] = {
    ".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".gif": "gif", ".webp": "webp", ".pdf": "pdf",
    ".webm": "webm", ".mp4": "mp4", ".mp3": "mp3", ".ogg": "ogg", ".wav": "wav",
}
HEAD: Final = 16


PREFIX_KIND: Final[tuple[tuple[bytes, Kind], ...]] = (
    (b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF87a", "gif"), (b"GIF89a", "gif"), (b"%PDF-", "pdf"),
    (b"\x1aE\xdf\xa3", "webm"), (b"OggS", "ogg"), (b"ID3", "mp3"), (b"\xff\xfb", "mp3"), (b"\xff\xf3", "mp3"), (b"\xff\xf2", "mp3"),
)


def sniff(head: bytes) -> Kind | None:
    """The kind the leading bytes say, None for anything else."""
    if head.startswith(b"RIFF"):
        return "webp" if head[8:12] == b"WEBP" else "wav" if head[8:12] == b"WAVE" else None
    if head[4:8] == b"ftyp":
        return "mp4"
    return next((kind for prefix, kind in PREFIX_KIND if head.startswith(prefix)), None)


def check_fields(name: str, caption: str, role: str) -> Role:
    """name, caption and role as the model gave them; the role."""
    found = next((r for r in ROLES if r == role), None)
    if found is None:
        raise Refused(f"role must be one of {', '.join(ROLES)}; got {role!r}")
    if not caption.strip():
        raise Refused("caption is required: say what the file shows")
    if len(caption) > CAPTION_MAX:
        raise Refused(f"caption is {len(caption)} characters; the limit is {CAPTION_MAX}")
    if (not name or len(name) > NAME_MAX or name.startswith(".") or ".." in name or not set(name) <= NAME_CHARS
            or os.path.basename(name) != name):
        raise Refused(f"name {name!r} must be a plain file name of up to {NAME_MAX} characters (letters, digits, . _ - and space; "
                      "no folders, no '..', no leading dot), e.g. home.png")
    if Path(name).suffix.lower() not in SUFFIX_KIND:
        raise Refused(f"name {name!r} needs one of the suffixes {', '.join(SUFFIX_KIND)}")
    return found


def check_file(src: Path, name: str) -> Kind:
    """The file is a non-empty regular file under the size cap whose bytes are what its name's suffix says; its kind."""
    if src.is_symlink() or not src.is_file():
        raise Refused(f"{src} is not a regular file")
    size = src.stat().st_size
    if size == 0:
        raise Refused(f"{src.name} is empty; write the file fully before registering it")
    if size > MAX_BYTES:
        raise Refused(f"{src.name} is {size >> 20} MB; the limit is {MAX_BYTES >> 20} MB")
    with src.open("rb") as f:
        kind = sniff(f.read(HEAD))
    if kind is None:
        raise Refused(f"{src.name} is not a supported type (png, jpg, gif, webp, pdf, webm, mp4, mp3, ogg, wav by its first bytes)")
    want = SUFFIX_KIND[Path(name).suffix.lower()]
    if kind != want:
        raise Refused(f"the file is a {kind} but name {name!r} says {want}; rename it to a .{kind} name")
    return kind


def source(cwd: Path, path: str) -> Path:
    """`path` (relative to `cwd`, or absolute) as a real file inside `cwd`: no symlink on the way, no secret-looking name."""
    root = Path(os.path.realpath(cwd))
    given = Path(path)
    p = given if given.is_absolute() else root / given
    try:
        rel = Path(os.path.normpath(p)).relative_to(root)
    except ValueError:
        raise Refused(f"{path} is outside the working folder {root}") from None
    walk = root
    for part in rel.parts:
        walk = walk / part
        if walk.is_symlink():
            raise Refused(f"{path} is or passes through a symlink ({walk.name}); symlinks are refused")
        if any(fnmatch.fnmatch(part.lower(), pat) for pat in SECRET_NAMES):
            raise Refused(f"{path} looks like a secret ({part}); it will not be registered")
    if not walk.is_file():
        raise Refused(f"no such file: {path}")
    return walk
