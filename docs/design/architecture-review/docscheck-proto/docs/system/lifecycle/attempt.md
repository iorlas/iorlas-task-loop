---
# Status: evidence; historical format specimen, not current system authority
entity: term/attempt
owner: area/engine
source: "src/taskloop/factory_schema.py::sql:attempt.phase"
initial: admitted
terminal: [captured]
states: [admitted, dispatching, registered, captured]
events: [dispatch, register, capture, process-death, restart]
transitions:
  - {from: admitted, event: dispatch, to: dispatching}
  - {from: admitted, event: process-death, to: admitted}
  - {from: admitted, event: restart, to: admitted}
  - {from: dispatching, event: register, to: registered}
  - {from: dispatching, event: process-death, to: dispatching}
  - {from: dispatching, event: restart, to: dispatching}
  - {from: registered, event: capture, to: captured}
  - {from: registered, event: process-death, to: registered}
  - {from: registered, event: restart, to: registered}
---
