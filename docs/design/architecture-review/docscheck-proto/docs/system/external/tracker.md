---
# Status: evidence; historical format specimen, not current system authority
owns_facts: [requirements, dependencies, questions, answers, discussion, task state]
port: src/taskloop/tracker_client.py
used_by: [area/engine]
rules:
  - {id: 1, applies_to: "every module outside tracker_client.py", holds: "reaches the tracker client through its port and constructs none", check: check/test_only_tracker_client_constructs_the_tracker_client}
  - {id: 2, applies_to: "a task state change", holds: "goes through a typed tracker operation; a comment changes no state"}
failures:
  - {when: "a tracker read fails during admission", outcome: outcome/AdmitUnavailable}
---
