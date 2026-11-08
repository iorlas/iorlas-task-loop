"""Recording landing capabilities without the production lander's import graph."""
from tlkernel.bead import Bead


class FakeLandStage:
    """A configurable stage and factory; each operation records its arguments."""

    def __init__(self, host: object = None, *, sha: str = "", green: bool = True, result: object = None) -> None:
        self.host = host
        self.sha, self.is_green, self.result = sha, green, result
        self.calls: list[tuple[str, object]] = []
        self.hosts: list[object] = []
        self.out = self
        self.gate = self

    def __call__(self, host: object) -> FakeLandStage:
        self.hosts.append(host)
        return self

    def wip_push(self, i: int) -> None:
        self.calls.append(("wip_push", i))

    def green(self) -> bool:
        self.calls.append(("green", None))
        return self.is_green

    def run(self) -> object:
        self.calls.append(("run", None))
        return self.result

    def finish(self, bead: Bead) -> str:
        self.calls.append(("finish", bead))
        return self.sha
