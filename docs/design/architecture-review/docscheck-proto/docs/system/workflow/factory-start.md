---
# Status: evidence; historical format specimen, not current system authority
goal: "Rounds run against an intact factory.db with every unfinished attempt reconciled."
actors: [persona/owner]
areas: [area/storage, area/engine]
externals: [external/tracker, external/git]
steps:
  - {do: "start the rounds process", actor: persona/owner}
  - {do: "open factory.db and act on its state as the cases in table start say", actor: area/storage}
  - {do: "observe every registered entry process and record each attempt's next action", actor: area/engine, causes: lifecycle/attempt, event: process-death}
  - {do: "relaunch the entry process of an admitted attempt whose entry is gone", actor: area/engine, causes: lifecycle/attempt, event: restart}
  - {do: "read approved ready tasks from the tracker", actor: external/tracker}
  - {do: "dispatch the agent of a newly admitted attempt through its entry process", actor: area/engine, causes: lifecycle/attempt, event: dispatch}
---
