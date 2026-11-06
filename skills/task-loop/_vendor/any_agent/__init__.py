"""Headless agent CLIs (claude, codex, opencode) behind one Harness protocol, supervised to a classified outcome.

A harness builds the launch and parses the CLI's stream into typed events once; `run` spawns it in a session of its own, watches it
(silence, first event, answer grace, stall, a limit its own log reports, the network) and stops its whole tree; `classify` turns what the
vendor said into one reason. Callers inject what they own: the live sink, the lane-gone check, the secret policy, the network probe.
"""

from any_agent import events, vendors
from any_agent.classify import Outcome, classify
from any_agent.harnesses.claude import ClaudeHarness
from any_agent.harnesses.codex import CodexHarness
from any_agent.harnesses.opencode import OpenCodeHarness, Profile
from any_agent.protocol import Evidence, Harness, LaunchInputs, LaunchSpec, Summary
from any_agent.supervisor import LiveSink, LogWatcher, NullSink, RunHooks, RunOutcome, Stop, Supervisor, run
from any_agent.watch import Limits

__all__ = [
    "ClaudeHarness",
    "CodexHarness",
    "Evidence",
    "Harness",
    "LaunchInputs",
    "LaunchSpec",
    "Limits",
    "LiveSink",
    "LogWatcher",
    "NullSink",
    "OpenCodeHarness",
    "Outcome",
    "Profile",
    "RunHooks",
    "RunOutcome",
    "Stop",
    "Summary",
    "Supervisor",
    "classify",
    "events",
    "run",
    "vendors",
]
