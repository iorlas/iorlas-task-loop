"""The dash wired together: every reader and every endpoint of the server, made once over one Env and handed to each other.
A test makes its own `Dash` over a temp config dir and fake ports."""

from taskloop_dash.api.artifacts import Artifacts
from taskloop_dash.api.liveview import Live
from taskloop_dash.api.looks import Looks
from taskloop_dash.api.reads import Reads
from taskloop_dash.api.writes import Writes
from taskloop_dash.env import Env
from taskloop_dash.readers.beads import Beads
from taskloop_dash.readers.records import Records
from taskloop_dash.readers.runlogs import RunLogs
from taskloop_dash.readers.world import Worlds


class Dash:
    def __init__(self, env: Env) -> None:
        self.env = env
        self.records = Records(env)
        self.beads = Beads(env, self.records)
        self.runlogs = RunLogs(env.files)
        self.looks = Looks(env, self.records, self.beads)
        self.artifacts = Artifacts(env)
        self.live = Live(env, self.records)
        self.reads = Reads(env, Worlds(env, self.records, self.beads, self.runlogs, self.looks))
        self.writes = Writes(env, self.records, self.beads, self.looks)
