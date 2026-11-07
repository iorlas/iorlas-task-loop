"""The dash wired together: every reader and every endpoint of the server, made once over one Env and handed to each other.
A test makes its own `Dash` over a temp config dir and fake ports."""

from tldash.api.artifacts import Artifacts
from tldash.api.liveview import Live
from tldash.api.looks import Looks
from tldash.api.reads import Reads
from tldash.api.writes import Writes
from tldash.env import Env
from tldash.readers.beads import Beads
from tldash.readers.records import Records
from tldash.readers.world import Worlds


class Dash:
    def __init__(self, env: Env) -> None:
        self.env = env
        self.records = Records(env)
        self.beads = Beads(env, self.records)
        self.looks = Looks(env, self.records, self.beads)
        self.artifacts = Artifacts(env)
        self.live = Live(env, self.records)
        self.reads = Reads(env, Worlds(env, self.records, self.beads, self.looks), self.artifacts)
        self.writes = Writes(env, self.records, self.beads, self.looks)
