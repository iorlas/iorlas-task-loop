# In-memory settlement probe

Status: **evidence**. Dated findings, measurements and their limits, retained with the original commands and
environment. This is not a current setup runbook; use the [README](../../../README.md) for implemented commands.

Executed 2026-11-09 from the review worktree with `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python`.
This uses the actual Settle and effect interpreter with an in-memory refused close and cleanup callbacks.
It does not contact a task service, run Git, release a real slot or delete a checkpoint. It reproduces the
failure propagation/marking behavior, not a complete production incident or every cleanup implementation.

The probe executed successfully and observed the rejected close still marked applied, followed by the cleanup
callbacks. The initial `uv run --no-sync` invocation could not acquire a cache lock in the sandbox; using the
already-installed interpreter required no dependency sync or escalation. No production source/test edits.

## Probe

Run the following in the current repository environment; imports deliberately use this tree's source.

```python
import json
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path[:0] = [str(Path.cwd() / "src"), str(Path.cwd() / "skills/task-loop/_vendor"), *[str(p) for p in Path("packages").glob("*/src")]]
from tlkernel import closeeffects as effects, effectinterpret, fence, runoutcome as outcomes
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlpipeline.closing_settle import Settle
warnings, cleanup, close_calls = [], [], []
host = SimpleNamespace(bead=BeadId("audit-1"), claim=fence.offline(BeadId("audit-1")), store=object(), cfg=SimpleNamespace(base="origin/main"), run_id="audit-run", plan_summary="audit", disp=None, comment=lambda _: None, warn=warnings.append)
def refuse_close(*args):
    close_calls.append("close refused")
    return 1
settle = Settle(host, SimpleNamespace(close=refuse_close), object(), lambda *args: None, lambda *args: None)
done = outcomes.make(Kind.LANDED, sha="0123456789abcdef")
plan = [effects.CloseBead(landed=True), effects.ReleaseSlot(branch="task/audit-1", slot_gen=0), effects.DropCheckpoint()]
ledger = effectinterpret.MemoryLedger()
def apply(effect):
    if isinstance(effect, effects.CloseBead):
        settle.run(done, "audit")
    else:
        cleanup.append(effects.name_of(effect))
effectinterpret.interpret("audit-1", "audit-run", plan, ledger, apply)
print(json.dumps({"close_calls": close_calls, "warnings": warnings, "applied_keys": sorted(ledger.applied()), "cleanup_callbacks": cleanup, "scope": "Actual Settle and effect interpreter; in-memory refused task close and cleanup callbacks; no Git, task-service or filesystem cleanup operations"}, indent=2))
```

## Observed result (scope description omitted)

```json
{
  "close_calls": ["close refused"],
  "warnings": ["bd refused to close audit-1 (exit 1): close it by hand"],
  "applied_keys": [
    "audit-1/audit-run/close_bead",
    "audit-1/audit-run/drop_checkpoint",
    "audit-1/audit-run/release_slot"
  ],
  "cleanup_callbacks": ["release_slot", "drop_checkpoint"]
}
```
