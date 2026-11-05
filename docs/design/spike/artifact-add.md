# artifact_add spike: stdio MCP tool on claude, codex, opencode (2026-11-05)

Question (tl-jvpm.19): does a per-call stdio MCP child serving `artifact_add(path, caption, role, name)`, bound to bead/run/stage/attempt by its argv, work on all three harnesses under the flags delegate runs them with today?
Server: `docs/design/spike/artifact-add-server.py` (stdlib only, throwaway). Versions: claude 2.1.296, codex-cli 0.162.1, opencode 1.19.4; delegate 0.56.1 flags.

## Verdict
All three pass. No harness blocks the design. Codex, the expected failure, works: the MCP child is a plain subprocess of the codex client, outside the workspace-write sandbox, so no localhost and no extra sandbox hole is needed.

## Matrix (two runs each: "call artifact_add on out.png"; then bad names, extra ids, retry)
| check | claude -p | codex exec | opencode run |
|---|---|---|---|
| tool listed | yes (`mcp__spike__artifact_add`, init event) | yes | yes (`spike_artifact_add`) |
| tool called by the model | yes | yes | yes |
| file + sidecar in store | yes | yes | yes |
| binding ids correct | yes (from argv) | yes | yes |
| ids not model-passable | yes: extra `bead`/`run` args accepted by the harness, ignored by the server | same | same |
| `../x.png` and `/tmp/x.png` as name refused | yes | yes | yes |
| error reaches the model, it retries | yes (`is_error: true`) | yes (text only, see below) | yes (state `error`) |

Server-side checks (direct JSON-RPC test, harness-independent): symlink path refused, path outside cwd refused, non-image text file refused (magic bytes), bad role refused, over-long caption refused.

## Config each harness needs
Binding is in the server's argv: `--bead --run --stage --attempt --store --cwd`. The server is spawned per run by the harness client.

- claude: add `--mcp-config <file>` next to the existing `--strict-mcp-config`: `{"mcpServers":{"spike":{"command":"python3","args":[server,...binding]}}}`. The tool must be allowed: `--settings` with `{"permissions":{"allow":["mcp__spike__artifact_add"]}}`. `--tools` (built-in list) does not affect MCP tools. Name seen by the model: `mcp__<server>__artifact_add`.
- codex: two more `-c` flags after CODEX_ACCESS: `-c 'mcp_servers.spike.command="python3"' -c 'mcp_servers.spike.args=["server.py","--bead",...]'`. `--ignore-user-config` does not drop `-c` MCP entries. With `-s workspace-write`, network off, `approval_policy=on-request`, `approvals_reviewer=auto_review`: no approval prompt for the tool in these runs.
- opencode: in `OPENCODE_CONFIG_CONTENT` add `"mcp":{"spike":{"type":"local","command":["python3",server,...binding],"enabled":true}}` and a permission for `spike_artifact_add`. The spike ran with `"permission":{"*":"deny","read":"allow","spike_artifact_add":"allow"}` and it worked; delegate's own `"*":"allow"` should cover the tool but was not run (this session's classifier refused an allow-all agent). Empty `XDG_CONFIG_HOME` and `OPENCODE_DISABLE_*` env as delegate sets them. `--pure` does not block MCP. Tool name: `<server>_artifact_add`.

## Findings that change the design
1. The MCP child runs unsandboxed on codex (it wrote the store outside the workspace) and on claude/opencode (they sandbox only commands). The server's own realpath, symlink, name and magic checks are the only guard; keep them in the real server.
2. Harnesses pass unknown arguments through. Declare `additionalProperties: false` in the input schema and ignore extras (the spike ignores them).
3. Codex's json event for an MCP call shows `error: null` even for a refusal (the text is in `result.content`); claude and opencode flag it. Anything that reads the transcript for tool failures cannot rely on codex's error field. The model still sees the text and retried.
4. The tool names differ per harness (`mcp__spike__x`, `spike_x`, server `spike` tool `x`). A prompt must say "artifact_add", not a full name; all three models resolved it.
5. opencode free model `deepseek-v4.1-flash-free` hit "Free usage limit reached"; the spike ran on `openai/gpt-6.1-terra`. The `openai/gpt-5.x` models are refused on this ChatGPT account.
6. Not tested: resume sessions (`codex exec resume`, `--resume`) with the MCP flags; startup cost per call (a python child, no Defender measurement); concurrent runs sharing one store; opencode's sandboxed `SHELL` wrapper (not set in the spike); Linux.
