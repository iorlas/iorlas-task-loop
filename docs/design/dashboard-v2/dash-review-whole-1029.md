# Whole-design review, 2026-10-29

Reviewers: Fable, Sonnet, ChatGPT (Codex), independently, on 1k card + 2b asks + 3b bead drawer. Merged by Opus.

## Agreed by all three (apply)
1. Bead drawer covers the decisions drawer. Opening a bead collapses decisions to a narrow rail with the 🙋 count; an ask card links to its bead; a bead with an open ask shows that ask inline. Never both open.
2. Colour contract, written once: teal = live/running now; red = trouble only (stuck, exited, tokens ≥4×); amber = watch (≥2×, send-backs); violet = tokens; "needs you" is not red. Live pass tab dot becomes teal.
3. Emoji collisions: tool icons never reuse stage emoji (Edit tool 📝, not ✏️); replan outcome 🔁, not 🧭; note to worker ✉️, not 💬 (💬 stays Ask back); ⏸ = parked (by ask or by owner), the parked strip says which.
4. One vocabulary: slot, pass, ask; panel "🙋 Decisions / Resolved"; one bead id format everywhere.
5. Now box: test row hidden until a results file exists; burn rate cut for v1.
6. Tool-call count shows failures ("14 calls · 1 failed"); Fable adds per-kind counts.
7. Note label says what happens: "comment, every later stage reads it", with an ETA to the next stage.
8. No separate bead page: the drawer is the bead page, with a deep link and a full-width option.
9. Next round = integration shell: nav, slots, Up next / queue, parked strip, landed strip, decisions dock, drawer, first-run/empty states. Never drawn together yet.

## Missing for week one (2-3 of 3)
- Up next / queue and "why is nothing picked up" (3/3).
- States: offline/stale, worker exited (💀, not 🛑), error, no baseline yet (3/3).
- Deep links for bead/pass/stage; drawer survives reload (2/3).
- One view across machines: per-machine dashboards mean several URLs on the phone (Sonnet, strong).
- Push notification on ask/stuck (Sonnet).

## Mock bugs found (Opus's)
- Pass ③ tab showed messages from passes ① and ②; each pass tab must filter, cross-pass timeline goes to 📄 Bead.
- Live re-render collapsed opened tool lists.
- Drawer header total hardcoded, not computed.

## Challenges to owner decisions
- Tint by share of the bead: old cells change colour as new passes arrive (Sonnet). Fix: absolute token bands (ChatGPT, round 1j).
- Baseline = median of first 5 landed beads: skewed by small beads, not comparable across model lanes (ChatGPT, Sonnet). Fix: per-lane baseline, show sample size, advisory until enough.
- Per-stage marks (corner triangle, burn rate, per-stage limits) need per-stage baselines nobody decided (Fable, ChatGPT). Fix: v1 uses bead-level usual and fixed per-stage silence limits; triangle later.
- Ask-back cap of 3: cut, keep the count only (Fable, ChatGPT).
- Send & restart stage: ship (Sonnet) vs defer (Fable, ChatGPT).

## Rejected
- Emoji 🍎🐧🪟 for machines (Sonnet): 🍎 reads as fruit; keep the small monochrome icons.
- Blocking instant answers from collapsed cards (ChatGPT): owner chose speed with 5 s undo; the ⭐ shows its consequence line.
