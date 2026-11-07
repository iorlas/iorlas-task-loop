"""Release hand-over notes and process replacement bound to a config directory."""
from collections.abc import Sequence

from taskloop.app.release import reexec
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import NetPause, ReexecNote


class ReexecBook:
    def __init__(self, cfg: ConfigDir) -> None:
        self.cfg = cfg

    def net_pause(self, pause: NetPause) -> None:
        reexec.net_pause_store(self.cfg, BeadId(pause.bead)).write(pause)

    def note(self, note: ReexecNote) -> None:
        reexec.reexec_store(self.cfg, BeadId(note.bead)).write(note)

    def args(self, argv: Sequence[str], slot: str, wt: str) -> list[str] | None:
        return reexec.reexec_args(argv, slot, wt)

    def drop(self, bead: BeadId) -> None:
        reexec.drop_reexec(self.cfg, bead)

    def exec(self, argv: list[str], env: dict[str, str]) -> None:
        reexec.exec_in_place(argv, env)
