# Shelf proposal: any-agent offers the effort levels (ledger L44)

Status: proposed. The owner decides (values 11, 12).

## Gap

`any_agent` (pinned `46aa5a5`) passes `LaunchInput.effort` through as a bare string (`protocol.py`: `effort: str`; codex
`-c model_reasoning_effort=...`, claude `--effort`, opencode a variant argument). It exposes no list of the levels a harness
and model offer. The factory checks only that the value is one printable word, so a wrong level (`--plan-effort hgih`)
reaches the agent and fails inside the vendor CLI, classed as a vendor failure (self-hosting trial 3, F2).
The levels exist only in vendor state: Codex lists them per model in `~/.codex/models_cache.json`.
The factory must not hard-code a list (it differs by model and CLI version, e.g. `ultra` only for `gpt-6.1-sol`).

## Proposal

In `any_agent`, per harness, one read-only call that returns what the installed CLI offers for a model:

```python
class EffortLevels(BaseModel):
    model: str
    levels: tuple[str, ...]      # in the vendor's order, lowest first
    default: str | None          # the level the CLI uses when none is asked

def effort_levels(harness: HarnessKind, model: str, home: Path) -> EffortLevels | None
```

- `None` = the harness cannot tell (unknown model, no cache, CLI without a list). Unknown is not "any".
- Codex reads `models_cache.json` under the given `home` (explicit home, as the other any_agent ports); Claude and OpenCode
  return what their CLIs document, or `None`.

## Factory use once it exists

`AgentSetting` stays a pure value. The check runs at configuration time in the one place that already resolves the machine
file and flags (`config show`, `step start`, `rounds once|start`): a level outside `levels` is a typed refusal
(`Failed("refused", "choices", ...)`) with the generic message "effort X is not offered for model M; offered: ...".
The vendor's detail stays in the adapter. `None` from the harness means the factory says "unverified" and starts anyway
(fail-in-the-open, no guess).

## Why not now

Inventing a list in the factory would be a second owner of a vendor fact (value 4) that rots with each CLI release.
