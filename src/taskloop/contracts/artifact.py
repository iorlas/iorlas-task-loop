"""The artifact store's records: where a stage attempt keeps its files, and the sidecar that makes a file an artifact.

Layout: <config>/artifacts/<repo>/<bead>/<run>/<stage>-<attempt>/<name> with <name>.json beside it. The directory is the index
(no table in factory.db); a file without a sidecar is not an artifact. Written by app/artifacts/store.py, read by the dashboard."""
from typing import ClassVar, Final, Literal

from taskloop.contracts.wire import Rec

type Role = Literal["before", "after", "progress", "result"]
type Kind = Literal["png", "jpg", "gif", "webp", "pdf", "webm", "mp4", "mp3", "ogg", "wav"]

ROLES: Final[tuple[Role, ...]] = ("before", "after", "progress", "result")
CAPTION_MAX: Final = 200
SIDECAR_SUFFIX: Final = ".json"


class ArtifactSlot(Rec):
    """Where one stage attempt's artifacts go; the tool server is bound to one by its argv, never by the model."""

    repo: str
    bead: str
    run: str
    stage: str
    attempt: int


class ArtifactMeta(Rec):
    """The sidecar: what the file is. `created` is UTC epoch seconds (recency; a copy resets mtime), `kind` comes from the magic bytes."""

    V: ClassVar[int] = 1
    name: str
    caption: str
    role: Role
    kind: Kind
    size: int
    sha256: str
    created: float
