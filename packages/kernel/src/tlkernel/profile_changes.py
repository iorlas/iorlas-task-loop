"""The owner's audit row authorizing delivery of one profile patch."""
from tlkernel.wire import Rec


class ProfileChange(Rec):
    t: float
    owner_text: str
    repo: str
    branch: str
    tip: str
    base: str
    diff_sha: str
    pid: int
