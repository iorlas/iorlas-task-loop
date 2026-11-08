"""Names and times the task view prints: accounts by family, models, clock times. No regex: the engine's own text is
split with str methods."""

import time
from typing import Final

IMAGES: Final = ("image/png", "image/jpeg", "image/gif", "image/webp")
# The one table of what is served by its name; the host's mime database (/etc/mime.types) answers differently per machine.
TYPES: Final = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
    "mp4": "video/mp4", "webm": "video/webm", "ogv": "video/ogg",
    "mp3": "audio/mpeg", "wav": "audio/vnd.wave", "ogg": "audio/ogg", "m4a": "audio/mp4", "aac": "audio/aac", "flac": "audio/flac",
    "pdf": "application/pdf",
}


def content_type(name: str) -> str:
    """The type a file name is served as, from TYPES by its extension; '' for any other (it downloads)."""
    return TYPES.get(name.rpartition(".")[2].lower(), "") if "." in name else ""


def kind_of(name: str) -> str:
    """'image' (shown inline), 'pdf' (opens in a tab) or 'file' (download only: HTML is never run as a page)."""
    ctype = content_type(name)
    return "image" if ctype in IMAGES else "pdf" if ctype == "application/pdf" else "file"


def num(ident: object) -> int:
    """The number in a step id ('n4' -> 4); 0 for none."""
    digits = str(ident or "").lstrip("nc")
    return int(digits) if digits.isdigit() else 0


def account_name(account: str | None = "", family: str | None = "") -> str:
    """Delegate's family, or the account name's first part, title-cased."""
    return (family or (account or "").split("_")[0]).title()


def hhmm(t: float | None) -> str:
    return time.strftime("%H:%M", time.localtime(t)) if t else ""


def when(t: float | None) -> str:
    """HH:MM today, else the weekday too."""
    if not t:
        return ""
    same = time.strftime("%Y%m%d", time.localtime(t)) == time.strftime("%Y%m%d")
    return hhmm(t) if same else time.strftime("%a %H:%M", time.localtime(t))
