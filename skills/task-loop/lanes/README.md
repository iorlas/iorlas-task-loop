# lanes

Delegate link, call state, net gate, lane policy, transcripts, opencode readers (E2).

- `call.py`: `Idle` (the write-idle watcher), `live_file`, `agent_run_session`, `file_mtime`.
- `route.py`: `find_route`, `lane_status`, `contract`, `access`, `ROLES` (delegate's route.py and its handshake).

Moved here unchanged by E2 (84-self-hosting sec 2.4). Process running and killing is in `core/procs.py`. The rest of the folder
(lane policy, call state, net gate, delegate link) arrives with its release. Allowed imports: tests/test_layers.py.
