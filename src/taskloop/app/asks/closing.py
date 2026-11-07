"""Ask validation and park transitions bound to a closing run's config directory."""
from taskloop.app.asks import parks, raiser, trustroots
from taskloop.contracts.bead import Bead
from taskloop.contracts.delegate import Permanence
from taskloop.contracts.gitport import Git
from taskloop.contracts.kinds import Kind
from taskloop.contracts.parks import Park
from taskloop.contracts.paths import ConfigDir
from taskloop.domain.asks.spec import AskSpec
from taskloop.domain.lanes.pause_reasons import Producer


class ClosingAsks:
    def __init__(self, cfg: ConfigDir) -> None:
        self.cfg = cfg

    def problems(self, spec: AskSpec) -> list[str]:
        return raiser.problems(spec)

    def paused(self, bead: Bead, kind: Kind, run: str, now: float, *, reason: str = "",
               not_before: float = 0.0, fingerprint: str = "", producer: Producer | None = None,
               permanence: Permanence | None = None) -> Park | None:
        return parks.paused(self.cfg, bead, kind, run, now, reason=reason, not_before=not_before,
                            fingerprint=fingerprint, producer=producer, permanence=permanence)

    def ended(self, bead: Bead, kind: Kind, run: str, now: float) -> None:
        parks.ended(self.cfg, bead, kind, run, now)


class ClosingTrust:
    def refusal(self, git: Git, wt: str, base: str, bead: Bead | None) -> str:
        return trustroots.refusal(git, wt, base, bead)
