# Reduce the fixed context of factory Codex attempts

Task: `tl-8bh9.14.176`. Status: proposed; implementation and measurement pending.

## Intended result

Factory Codex launches explicitly disable the automatic skill instructions,
multi-agent collaboration and plugin recommendations using documented per-run
options. Apply these choices to each new attempt, without changing `~/.codex`,
`CODEX_HOME`, repository instruction files or other harnesses.

The requested measurement is first-call input of 14,500 tokens or less on three
attempts, against the supplied baseline of about 17,208. That result is unproven:
the documentation does not establish switches for every requested reduction.
Retain unsupported blocks and report their cost instead of inventing options or
claiming the expected 3% saving before measuring it.

## Current implementation

At source commit `614fa5b4cbadee30fc0bed29f0b9000262dfd4a1`,
`src/taskloop/agents/launch.py` owns `FactoryCodexAccess.config()` and
`codex_access()`. Both workspace-write and full-access policies already use this
factory subclass. Its codec delegates to the released `CodexAccess.config()`
and adds the explicit empty writable-roots override where needed.

`AgentLaunch.build()` supplies this access policy to the released Codex harness.
The existing dependency is `any-agent==0.10.0`; the local subclass can append
`-c key=value` arguments without a shelf release. Keep the existing approval,
sandbox, shell environment, rules and user-config settings intact.

The slot is the assigned task worktree. It has no changes beyond the source
commit and no unfinished task commit to recover. This plan changes no runtime
code and launches no model attempts.

## Documented options and limits

Documentation inspected on 2026-11-14:

- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
- [One-off CLI overrides](https://learn.chatgpt.com/docs/config-file/config-advanced#one-off-overrides-from-the-cli).
- [Codex CLI reference](https://developers.openai.com/codex/cli/reference/).
- [Project instruction discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

The installed executable reports `codex-cli 0.162.1`. Its built-in `codex --help`
documents `-c` and the equivalence of `--disable NAME` to
`-c features.NAME=false`; `codex features list` documents the available names,
stages and effective states. These are CLI documentation, not inferred keys.

| Requested reduction | Documented option or finding | Decision |
| --- | --- | --- |
| Automatic skills list/instructions | `skills.include_instructions` | Append `-c skills.include_instructions=false`; verify the whole automatic block disappears. |
| Multi-agent role/mode instructions | `features.multi_agent`; documented as controlling collaboration tools | Append `-c features.multi_agent=false`; verify instruction removal as well as tools. |
| Recommended plugins | Installed CLI advertises `recommended_plugins` as a stable feature | Append `-c features.recommended_plugins=false`. Its observed default is already false, so incremental savings may be zero. |
| Collaboration-mode instructions | Installed CLI lists `collaboration_modes` as removed; no supported removal setting found | Leave alone. Do not send a removed flag. |
| Trim generated AGENTS.md | No documented project-instruction content replacement setting found | Leave the generated Beads, Agent Context Profiles and Session Completion material intact. |
| Slot path near the start of AGENTS.md context | No documented instruction-header relocation setting found | Leave alone; do not promise improved shared-prefix caching. |

The documented project knobs `project_doc_max_bytes` and
`project_doc_fallback_filenames` control limits and discovery, not selective
replacement. `model_instructions_file` replaces built-in model instructions;
`developer_instructions` adds instructions. Neither documents the requested
project-instruction substitution. Do not use them to simulate one, truncate the
file at a byte boundary, create AGENTS.override.md, or strip prompt messages.

A read-only local probe with the three proposed `-c` arguments and
`features list` succeeded: `multi_agent` and `recommended_plugins` were false;
`collaboration_modes` remained removed/true. This proves feature selection,
not the resulting model context or token saving. `--strict-config` is explicitly
unsupported by `codex features`; do not use it as a validation gate there.

## Implementation

1. In `FactoryCodexAccess.config()`, append the three supported overrides after
   `super().config()` while preserving the empty-roots handling. Keep the keys
   at this Codex adapter boundary, with concise documentation references. Update
   the subclass docstring to describe both factory launch responsibilities.
2. Extend the existing launch contract coverage in
   `tests/steps/test_agent_launch.py`. Inspect the actual released harness's
   `LaunchSpec.argv` for the three explicit false values across both sandbox
   policies and prepared/unprepared launches. Verify preservation of existing
   permissions, roots, environment and ignore flags through the existing test.
   Avoid testing only a hand-built list returned by the same method.
3. Keep Claude/OpenCode launches and the task input/schema unchanged. Do not add
   a profile setting, new configuration owner, dependency, process wrapper,
   persistent harness configuration or transcript-driven control behavior.

If the implementation machine uses another Codex version, confirm these options
in that version's documentation before applying them. Do not silently replace
an unavailable option with a guessed key or upgrade the harness in this task.
Record the unsupported reduction here, as required by the task.

## Verification and measurement

For implementation, run the supplied `just check` and `just test` gates using
the successor environment. Launch contracts use fakes and the released codec;
do not run whole-suite/live harness tests or add a test that asserts an invented
token saving. No implementation gates are needed for this plan-only attempt.

After the changed factory is running, observe three ordinary, independently
admitted Codex attempts; do not create unrelated tasks or model calls just to
fill the sample. Keep the runtime version fixed until restart. Record in this
directory the source revision, CLI/model versions, session/attempt references,
step, slot, prompt size, first-call input tokens, cached input tokens and the
presence/absence of each requested instruction block. Inspect evidence through
its owning readers; use recorded structured usage, not display-text estimates,
attempt totals or log-derived workflow state. Preserve all original evidence.

Use the first completed model call's usage before any tool output or subsequent
conversation. Include the supplied baseline transcript reference
`01a1d8e1-8a3b-7ed1-b0a8-1e36022ad720` and its 17,208 input-token observation.
Keep task/context sizes comparable and disclose differences; if the CLI/model
changed, use a matching baseline before attributing the delta to these flags.
Report all three individual counts and their range, including zero cached
tokens. Do not subtract cached tokens from input to make the threshold pass.

Confirm from captured context that the skills block, multi-agent instructions
and recommended-plugins block are absent. A disabled tool flag alone is not
proof that its instructions were omitted. Report any surviving instructions as
an unsupported reduction unless another documented option establishes removal.
Verify the change writes no user configuration or generated AGENTS.md and does
not relocate the slot path through a workaround.

Implementation gates passing does not complete the measurement criterion. Mark
the numerical target met only when all three comparable attempts have at most
14,500 first-call input tokens. If permitted options leave counts above that,
record the actual saving and remaining blocks and report the criterion unmet;
an owner decision is then needed to accept the documented limit or change scope.
The supplied expected 1.7M-token/3% saving and caching improvement remain estimates
until supported by observations.
