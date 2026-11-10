# Shelf change request: beads-client 0.2.0, a ready-set read with its owning fake

For: the owner, who releases it (answer to Q4 of [the scheduling plan](plan.md)). Consumer: iorlas-task-loop,
tl-8bh9.4.3.1.13 (`tl plan next`). Written 2026-11-10 from a read-only look at the shelf: the tag `beads-client-v0.1.0`
(commit 3afd60d, "Preserve truthful task reads and provide a shared semantic fake (#67)") and the installed 0.1.0 wheel.
Nothing in the shelf was edited. **Base the change on the tag or `main`, not the local checkout**: the local shelf
working copy is on branch `pix-portability` (76f31d6), whose `packages/beads-client` predates the tag (no `reads.py`,
no `tests/test_task_read.py`).

## Why

The factory's scheduling round reads the tracker's ready set once per round (`Bd.ready(label)`, `bd ready -n 0
--label auto`) and the parents of candidates (`Bd.show`). CLAUDE.md requires a shared task fake to come from its owning
library. 0.1.0 already exposes `TaskReadClient` (`show`) with `FakeTaskReadClient` and `task_read_contract`; it has
no structural protocol or fake for `ready`. `Bd.ready` itself exists and is unchanged.

Readiness (open, no active blocker, not deferred, not in progress, not hooked) is bd's computed fact. The fake must
**not** compute it: the test seeds which records are ready and in which order, exactly as a consumer test needs it.

## The change (additive; no existing signature changes)

### 1. `src/beads_client/reads.py`: one more structural protocol

```python
class ReadyReadClient(Protocol):
    """Read the tracker's ready set: open, unblocked, undeferred records, in the tracker's own order. A label keeps only
    records carrying it. An empty result is []; any failure raises BdError (never an empty success)."""

    def ready(self, label: str = "", /) -> list[Bead]:
        """Return the ready records without modifying them or the backlog."""
        ...
```

`Bd.ready(self, label: str = "")` already satisfies it (positional-only in the protocol, so the parameter name does not
matter). Export `ReadyReadClient` from `beads_client/__init__.py` and add it to `__all__`.

### 2. `src/beads_client/testing.py`: `FakeTaskReadClient` gains the ready set

```python
class FakeTaskReadClient:
    def __init__(
        self,
        records: Iterable[Bead] = (),
        *,
        faults: Mapping[str, BdError] | None = None,
        ready: Iterable[str] = (),            # ids of seeded records that are ready, in the tracker's order
        ready_fault: BdError | None = None,   # raised by every ready() call (the whole read failed)
    ) -> None: ...
        self.ready_reads: list[str] = []      # the label of each ready() call, "" for none

    def ready(self, label: str = "") -> list[Bead]:
        """Deep copies of the seeded ready records carrying `label` (all when empty), in seeded order; `ready_fault`, when
        given, raises a fresh BdError with its kind, text and missing sections."""
```

Rules:

- An id in `ready` that is not a seeded record raises `ValueError` at construction (a ready row is a record).
- A duplicate id in `ready` raises `ValueError` at construction.
- Per-id `faults` apply to `show` only; they do not hide a record from `ready` (one ready call is one tracker read).
- `ready` returns snapshots: mutating a returned record or the seed never changes a later read (as `show` does now).
- `reads` keeps recording only `show` ids; `ready_reads` records labels. No runner, no mutation method.

### 3. `testing.py`: the shared contract

```python
def ready_read_contract(
    make: Callable[[tuple[Bead, ...], tuple[str, ...], BdError | None], ReadyReadClient],
) -> None:
    """Assert order, label filtering, empty results, decoded scheduling fields and typed failures."""
```

It asserts, against any `make(records, ready_ids, ready_fault)`:

1. **Order is the tracker's.** Seed three ready records in an order that is neither id nor priority order
   (`r-3` P2, `r-1` P0, `r-2` P1): `ready()` returns them in exactly that order.
2. **Label filter.** `ready("auto")` returns only records whose `labels` contain `auto`, still in order; a label no
   record carries returns `[]`.
3. **Not ready is absent.** A seeded record not in `ready_ids` never appears (whatever its status field says).
4. **Empty.** No ready ids: `ready()` is `[]`, not an error.
5. **Scheduling fields survive decoding.** `priority` (an int, and `None` when omitted), `parent`, `assignee`,
   `labels` (sorted tuple, as `bead_of` makes it) and `issue_type` equal the seeded values.
6. **Typed failures.** For each kind in `("malformed", "missing_binary", "timeout", "other")`, `ready()` raises
   `BdError` with that kind and nonempty text; never an empty success.
7. **Separate backlogs.** Two instances made from different seeds answer independently.

### 4. `tests/test_ready_read.py` (new), following `tests/test_task_read.py`

```python
def _real(records, ready_ids, fault) -> ReadyReadClient:
    # a controlled Runner standing in for bd 1.3.1:
    #   asserts argv == ["bd", "--actor", "reader", "ready", "-n", "0", *(["--label", L] if L else []), "--json"]
    #   and cwd == "/configured/backlog";
    #   fault: "malformed" -> exit 0 with "{}" (not a list of rows); timeout -> 124; missing_binary -> 127; other -> 1
    #   otherwise: exit 0 with json.dumps([asdict(r) for r in the ready records carrying L, in ready_ids order]),
    #   or "" when none (bd prints nothing for an empty ready set; `Bd._beads` already maps that to [])
    return Bd("reader", cwd="/configured/backlog", exe="bd", run=run)

def _fake(records, ready_ids, fault) -> ReadyReadClient:
    return FakeTaskReadClient(records, ready=ready_ids, ready_fault=fault)

@pytest.mark.parametrize("make", [_real, _fake], ids=["bd", "semantic-fake"])
def test_ready_reads_share_order_filter_and_failure_contracts(make): ready_read_contract(make)
```

Fake-only tests: `ready_reads` records labels; snapshot isolation; an unknown or duplicate ready id raises `ValueError`;
per-id `faults` do not affect `ready`. `test_boundary_beads_client.py` keeps passing (stdlib only, no consumer import).

Check the "malformed" reply shape against `classify.loads`/`beads_of` before writing the runner: `beads_of` treats a dict
with an `id` as one row, so the malformed reply must be a dict without `id` (`{}`) or a list holding a non-dict.

### 5. Package documents

- `CONTRACT.md`: one paragraph after the `TaskReadClient` paragraph: "`ReadyReadClient` exposes the existing
  `ready(label)` read: the tracker's ready set in its own order, label-filtered, `[]` when empty, `BdError` on any
  failure. `FakeTaskReadClient(..., ready=ids, ready_fault=...)` seeds readiness (never computes it);
  `ready_read_contract(make)` checks both." Add `tests/test_ready_read.py` to "Executable acceptance".
- `README.md`: one line under the testing section naming `ReadyReadClient` and the `ready=` seed.
- `CHANGELOG.md`: `- 0.2.0: existing Bd.ready -> structural ReadyReadClient; FakeTaskReadClient(ready=, ready_fault=)
  and ready_read_contract supply the owning ready-set seam.` (The 0.1.0 tag still shows its own lines as "Unreleased";
  label them 0.1.0 in the same edit if that is the shelf's convention.)

### 6. Shelf records, as the 0.1.0 release did

- `openspec/changes/ready-read-contract/` (`proposal.md`, `design.md`, `tasks.md`, `evidence.md`,
  `specs/beads-ready-read/spec.md`) and the merged `openspec/specs/beads-ready-read/spec.md` with three requirements:
  the ready set keeps the tracker's order and label filter; a failed read never becomes an empty success; consumers can
  exercise the same contract with a seeded in-memory fake that does not compute readiness.
- `catalog/beads-client.toml`: `release = "beads-client-v0.2.0"`; notes gain "Ready-set reads expose ReadyReadClient
  with a seeded semantic fake."
- `ledger/`: a new delivery entry (next `seq`) for `beads-client-v0.2.0`, consumer `iorlas-task-loop`, after the
  consumer adopts it; and its row in `ledger/README.md`.

## Version and release steps (owner)

1. `packages/beads-client/pyproject.toml`: `version = "0.1.0"` -> `"0.2.0"` (additive API: minor bump).
2. Shelf gates for the package (`just check`, the package's tests), review, merge to `main` as the 0.1.0 change was (#67).
3. Tag the merge commit `beads-client-v0.2.0` (annotated, as `beads-client-v0.1.0` is) and push the tag. These are remote
   publication steps; only the owner performs them.

## Our pin change (task-loop, after the tag exists)

`pyproject.toml`:

```toml
dependencies = [..., "beads-client==0.2.0", ...]          # was beads-client==0.1.0
[tool.uv.sources]
beads-client = { git = "https://github.com/yoselabs/shelf.git", subdirectory = "packages/beads-client", tag = "beads-client-v0.2.0" }
```

Then `uv lock` (only the beads-client entry changes: version and the tag's commit), the non-editable install the
justfile uses, `just check` and `just test` (existing tests use `FakeTaskReadClient(records)` and `show` only, which are
unchanged). The factory's `tracker.ReadyRows` is `class ReadyRows(TaskReadClient, ReadyReadClient, Protocol)`; `Bd` and
the fake satisfy it. No local `path=` source is ever committed (the shelf's commit guard refuses it); co-development
before the tag uses an uncommitted override only.

## Not verified

Read only: no shelf test was run and no runner reply was captured from a live `bd ready --label`; the "prints nothing
when empty" behaviour is taken from the existing `test_list_and_ready_empty_output_is_no_rows`.
