"""A bead's artifacts: the plain files its runs left in `ConfigDir.artifacts(bead)`, listed and served read only."""

import mimetypes
from pathlib import Path
from typing import Final

from taskloop.contracts.ids import is_bead_id
from taskloop_dash.env import Env
from taskloop_dash.views import names

INLINE: Final = names.IMAGES  # served as an image, a PDF as a PDF; the rest as a download
MAX_LIST = 200
kind_of = names.kind_of


class Artifacts:
    def __init__(self, env: Env) -> None:
        self.env = env

    def file(self, bead: str, name: str) -> tuple[bytes, str] | None:
        """One artifact's bytes and type; None for a bad name, a symlink, a missing file."""
        if not is_bead_id(bead) or not name or "/" in name or "\\" in name or name.startswith("."):
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
