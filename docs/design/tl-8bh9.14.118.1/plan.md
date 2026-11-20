# Header
Task: tl-8bh9.14.118.1; base: 9ee126d3db36fb48c12ba8fa5d2e4792552a9511.
Depth: small; one onboarding journey. Decisions: none missing; dependencies: landed. Evidence budget: 6 model calls.
Size: 2 changed files including plan; 1 independent behaviour; 35 implement model calls.

## Outcome and non-goals
Connect the existing installation and command reference into an ordered README walkthrough with concrete commands, consistent paths and observable checkpoints. Dependency declarations and tool pins already exist. Exclude runtime changes, new setup commands, dependency/version changes and CI.

## Settled decisions
- Keep manual land as the default and explain the explicit owner delivery action.
- Retain the no-CI decision and existing local checks, prek hook and factory checks.
- Use Codex's local file login and the existing slot adoption operation.
- Keep dependency and external-tool pins owned by their existing declarations.

## Open decisions
- None.

## Change map
- `README.md` — new onboarding walkthrough from installation through manual delivery.
- `src/taskloop/cli.py` — consult caller of `cli_step.register`.
- `src/taskloop/cli_step.py` — consult `register`, `_round_flags`, `_land_flags`, `_adopt`, `_land`: flag producers and operation callers.
- `src/taskloop/slots.py` — consult `folder_name`, `adopt`: slot naming and adoption.
- `src/taskloop/agent_credentials.py` — consult `codex_machine_credentials` and caller `machine_credentials`.
- `tests/steps/test_credentials.py` — consult helper calling `codex_machine_credentials`.
- `src/taskloop/machine_config.py` — consult `config_file`, `defaults`.
- `pyproject.toml` — consult `project.scripts` and declarations.

## Read list
- `README.md:1-49` — scheduling, inspection and land commands.
- `README.md:85-145` — holds, configuration and login expectations.
- `README.md:152-211` — installation, existing pins and slot path constraints.
- `src/taskloop/cli.py:135-155` — command registration integration.
- `src/taskloop/cli_step.py:50-109` — adoption, inspection and rounds registration.
- `src/taskloop/cli_step.py:112-177` — delivery and scheduling arguments.
- `src/taskloop/cli_step.py:259-275` — land and adoption callers.
- `src/taskloop/slots.py:118-179` — naming and adoption requirements.
- `src/taskloop/agent_credentials.py:36-58` — executable and local login requirements.
- `src/taskloop/agent_credentials.py:80-93` — harness dispatch caller.
- `tests/steps/test_credentials.py:35-58` — credential helper and assertions.
- `src/taskloop/machine_config.py:77-93` — config location and defaults.
- `pyproject.toml:5-39` — package and entry point.

## Contract
Intent: start on Linux with a writable origin, main and a committed profile. Effect: commands install prerequisites, authenticate Codex, initialize the tracker, create/adopt one detached slot and approve/advance one bounded task. Result: inspection exposes passed checks; summary and explicit land deliver the task and confirm closure. Explain separate tracker synchronization. Use consistent backlog and paths within the slot length limit. No types, states or storage change.

## Work packages
1. `README.md`: document obtaining mise, uv, just, Beads and prek, origin credentials, Codex file login, tracker initialization, hook setup, slot adoption and approval. Verify syntax against CLI definitions or authoritative tool documentation. Closes A1.
2. `README.md`: check paths, rounds, held-task guidance, passed checks, summary, land and closure without live mutations. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each. Closes A1.

## Acceptance behaviours
A1. A new operator follows the README through prerequisites, authentication, tracker and slot setup, approval and one landed task, recognizing success at each checkpoint without undocumented setup knowledge.
