"""The dash wired together: every reader and every endpoint of the server, made once over one Env and handed to each other.
A test makes its own `Dash` over a temp config dir and fake ports."""

from taskloop_dash.api.asks import Asks
from taskloop_dash.api.beads import BeadApi
from taskloop_dash.api.graph import Graph
from taskloop_dash.api.lanes import Lanes
from taskloop_dash.api.liveview import Live
from taskloop_dash.api.looks import Looks
from taskloop_dash.api.roadmap import RoadmapApi
from taskloop_dash.api.runs import RunsApi
from taskloop_dash.api.tasks import Tasks
from taskloop_dash.env import Env
from taskloop_dash.readers.beads import Beads
from taskloop_dash.readers.events import Events
from taskloop_dash.readers.loops import Loops
from taskloop_dash.readers.opencode import OpenCode
from taskloop_dash.readers.records import Records
from taskloop_dash.readers.runlogs import RunLogs


class Dash:
    def __init__(self, env: Env) -> None:
        self.env = env
        self.opencode = OpenCode(env.home)
        self.events = Events(env, self.opencode)
        self.records = Records(env)
        self.beads = Beads(env, self.records)
        self.runlogs = RunLogs(env.files)
        self.lanes = Lanes(env)
        self.asks = Asks(env, self.beads, self.lanes)
        self.tasks = Tasks(env, self.records, self.runlogs, self.asks, self.beads, self.lanes)
        self.loops = Loops(env)
        self.graph = Graph(env, self.records, self.beads, self.tasks, self.asks, self.loops)
        self.looks = Looks(env, self.records, self.beads)
        self.roadmap = RoadmapApi(env, self.records, self.beads, self.graph, self.tasks, self.asks, self.looks, self.runlogs)
        self.runs = RunsApi(env, self.records, self.runlogs, self.events, self.opencode)
        self.bead = BeadApi(env, self.records, self.beads, self.runlogs, self.tasks)
        self.live = Live(env, self.records, self.lanes)

    def reflections(self, hours: object) -> dict[str, object]:
        try:
            n = int(str(hours))
        except ValueError:
            n = 24
        return self.env.ports.reflections(max(1, min(n, 24 * 14)))
