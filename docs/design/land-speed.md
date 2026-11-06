# Land speed (tl-land)

Measured over ~84 land attempts: 46 landed, 25 gate-red, 7 conflict, 6 "Head branch was modified".

1. **Merge the judged commit.** Already so: `Stack.item` gates `oid`, `prepare` requires the PR head to equal it, and `gh pr merge` carries
   `--match-head-commit oid`. The 6 refusals are real pushes during a gate. A head that moved is now seen under the lock, before the
   merge, and judged once more (`HeadMoved`, `HEAD_TRIES = 2`); it is never merged unjudged.
2. **Gate independent PRs in parallel, merge serially.** `land-stack` prewarms: every open item is gated on the current base at once
   (bounded workers), then the serial loop runs as today under the land lock. The receipt key is (tree, base); after a merge the base
   moved, so the next item is a receipt miss and Carry decides (closure of the selected tests unchanged: the pass is carried, else
   the gate runs). Kill test: N=4 independent PRs land in about one gate time plus N carries.
3. **Main moved only in files the PR does not touch:** that is Carry's rule (same closure, same bytes); no second rule is added.
