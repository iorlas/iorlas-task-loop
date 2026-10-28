"""A bead's artifacts: the plain files its runs left in `ConfigDir.artifacts(bead)`, listed and served read only."""

import mimetypes
from pathlib import Path
from typing import Any, Final

from taskloop_dash.env import Env
from taskloop_dash.views import names

INLINE: Final = ("image/png", "image/jpeg", "image/gif", "image/webp")  # served as an image; the rest as a download
MAX_LIST = 200


def kind_of(name: str) -> str:
    return "image" if (mimetypes.guess_type(name)[0] or "") in INLINE else "file"


class Artifacts:
    def __init__(self, env: Env) -> None:
        self.env = env

    def listing(self, bead: str) -> list[dict[str, Any]]:
        """[{name, kind, size, at}], newest first. Symlinks and subdirectories are not listed."""
        if not names.is_bead_id(bead):
            return []
        out: list[dict[str, Any]] = []
        try:
            for p in self.env.config.artifacts(bead).iterdir():
                if p.is_file() and not p.is_symlink():
                    st = p.stat()
                    out.append({"name": p.name, "kind": kind_of(p.name), "size": st.st_size, "at": st.st_mtime})
        except OSError:
            return []
        return sorted(out, key=lambda a: -a["at"])[:MAX_LIST]

    def file(self, bead: str, name: str) -> tuple[bytes, str] | None:
        """One artifact's bytes and type; None for a bad name, a symlink, a missing file."""
        if not names.is_bead_id(bead) or not name or "/" in name or "\\" in name or name.startswith("."):
            return None
        p = Path(self.env.config.artifacts(bead), name)
        try:
            if p.is_symlink() or not p.is_file():
                return None
            data = p.read_bytes()
        except OSError:
            return None
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        return data, ctype if ctype in INLINE or ctype == "application/pdf" else "application/octet-stream"
