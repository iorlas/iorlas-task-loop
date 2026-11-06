# NOTIFY: a push when the factory needs the owner (tl-7i9k.10, R9-11)

Status: design note, 2026-11-06. Nothing here is built. It sends data outside the machine, so **the channel is the owner's decision** (below); the rest is shaped so any channel fits.

## Problem

An ask, a storm and a stopped loop are the three moments the factory waits for a person. Today the person finds out by opening the dashboard or `tl ask list`. A night with an ask at 01:00 wastes the hours until someone looks.

## What fires today (the three hooks already exist)

- **Ask.** An ask is a row put through `AskStore` (contracts/stores.py) and listed by the dashboard's Decisions view.
- **Storm.** `write_storm` (adapters/storm.py) files the fingerprint and the beads it quarantines; the loop shows a `LoopWait`.
- **Loop stop.** The loop writes `loop_exit` (`reason`, `detail`) to the event log (app/loop/core.py, contracts/events.py `LoopExit`).

The event log is the one place all three already pass, so the notifier is a reader of typed events, not a change to three call sites.

## Design

1. **A port, `Notifier.send(key, title, body)`**, with a fake for tests and one adapter per channel. The app layer owns the *when*; the adapter owns the HTTP call. One adapter is built first.
2. **What triggers**: `ask_opened` (one per ask id), `storm` (one per fingerprint), `loop_exit` with a reason other than `signal` from the owner (a crash, a stop for lack of disk, a budget stop). Nothing else; a notification that fires often gets muted.
3. **One message per cause.** The key is `ask:<id>`, `storm:<fingerprint>`, `exit:<loop pid>`. A sent key is a kv row `notify:<key>` (the same pattern as the receipts rows), so a restart or a second loop does not send twice. A failed send keeps no row and is tried again on the next tick, at most 3 times, then a warn line (never a stop of the loop).
4. **The text** is short and carries no repo path, no bead body, no secret: `ask tl-x1: <ask title, 80 chars>`, `storm: <fingerprint>, <n> beads held`, `loop stopped: <reason>`; the dashboard URL if the owner configured one. The owner reads the detail on the dashboard.
5. **Config.** `notify.channel` and `notify.url` live in `<config>/notify.json` (mode 0600, written by `tl notify set`), not in `.task-loop.json`: that file is checked in, and a topic URL is a secret (anyone who knows it reads and posts). Unset = off, no behaviour change.
6. **Test.** `tl notify test` sends one message and prints the answer, so the owner sees the phone buzz before trusting a night to it.

## Decision for the owner

Which channel? The adapter is about 30 lines whichever is chosen.

| channel | needs | secret | notes |
|---|---|---|---|
| ntfy.sh, public server | an app on the phone, a topic name | the topic (unguessable string) | simplest; the text passes through a third party, hence point 4 |
| ntfy, self-hosted | a server the phone can reach | topic + optional token | text stays on your host; one more service to keep up |
| Pushover | an account, an app token | token + user key | paid once; delivery receipts, priority |
| Telegram bot | a bot token, a chat id | bot token | works without a push app; the bot token is a long-lived secret |
| Mac notification only | nothing | none | only when the Mac is awake and in front of you: no help at night |

Recommendation: **ntfy.sh with an unguessable topic**, because it needs no account and the bead's own acceptance names it; move to self-hosted ntfy if you do not want the (short) text on a third party.

## Slices (one PR each, after the owner picks)

1. `Notifier` port, fake, `notify.json` reader, the kv dedupe row; table test for the three triggers and "twice is once".
2. The chosen adapter and `tl notify set|test`; a real-layer test against a local HTTP server.
3. The loop's tick calls it; a fake-clock loop test: an ask and a crash each send one message, a restart sends none.

## Decisions recorded

| Decision | Date |
|---|---|
| Open: the channel (table above). | - |
