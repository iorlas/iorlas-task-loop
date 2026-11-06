# Inner loop: pytest-testmon (opt-in; the gate stays `just test`)

`just test-inner <paths>` reruns only the tests whose code you changed, in the paths you name. It is for the minutes while you edit; it is **not**
a gate and changes nothing about `just test` (dev/affected.py picks the tests the gate runs, from the diff and the import graph).

```bash
just test-inner tests/land          # first run: runs them all and records which test touches which code (.testmondata, gitignored)
just test-inner tests/land          # after an edit in src/: only the tests that reach the changed functions
```

How it is wired: `uv run --with pytest-testmon` (no dependency added to pyproject.toml or uv.lock), `--testmon`, and `-o addopts="-p no:cacheprovider"`
because the repo's `-m 'not real and not e2e'` makes testmon switch itself off ("selection automatically deactivated because -m was used").
So real/ tests are included (e2e, live and delegate are ignored); name a narrow path.

What it does and does not see (measured on pix, testmon 2.3.0):
- a change to a function body in src/ or tests/: the tests that reach it rerun, the others are skipped;
- a comment-only change: nothing reruns (testmon compares code blocks, not comments);
- a changed `.py` test file reruns its tests; a previously failing test reruns every time until it passes;
- a config or data edit (pyproject.toml, `.importlinter`, `justfile`, golden files, `.task-loop.json`) is **not** a reliable trigger: the probe verdict is that
  testmon misses them. dev/affected.py has explicit rules for exactly these (its `strings`, `directories` and `config` rules), which is why it is the gate.

Use it to iterate; run `just check` and `just test` before you push.
