---
read_when: before changing admission, attempts, slots, rounds or the entry process
owns: ["src/taskloop/admit*.py", "src/taskloop/attempt*.py", "src/taskloop/slot*.py", "src/taskloop/round*.py"]
touches: [area/storage, external/tracker, external/git]
terms: [term/step, term/attempt, term/slot, term/admission, term/reservation, term/entry-process, term/dispatch, term/relaunch, term/capture, term/execution, term/hold]
rules:
  - {id: 1, applies_to: "an attempt", holds: "runs the agent at most once; a relaunch starts the entry process again and never dispatches again"}
  - {id: 2, applies_to: "rounds, the step operations and both entry processes", holds: "never import the land module; only the person's land command runs it", check: check/rounds-never-land}
  - {id: 3, applies_to: "an attempt row", holds: "has at most one reservation, unique on the attempt"}
  - {id: 4, applies_to: "one process signal", holds: "is installed only by the rounds process's SIGINT, SIGTERM and SIGHUP handlers", check: check/one-signal-owner}
outcomes:
  - {name: AdmitUnavailable, handled_in: area/engine, source: "src/taskloop/admit.py::AdmitUnavailable"}
operations:
  - {name: admit an attempt, source: "src/taskloop/admit.py::AttemptAdmission", outcomes: [outcome/AdmitUnavailable]}
  - {name: release a slot, source: "src/taskloop/slot_release.py::park_slot"}
commands:
  - {name: tl step start, runs: "src/taskloop/admit.py::AttemptAdmission", who: persona/owner}
evidence:
  - {artifact: "the attempt's captured result", path: "factory.db table execution", writer: area/engine, reader: [area/engine, persona/owner]}
---
