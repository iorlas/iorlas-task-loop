#!/bin/sh
case "$*" in "auth status") [ "$FAKE_MODE" = authout ] && echo '{"loggedIn": false}' || echo '{"loggedIn": true}'; exit 0;; esac
echo "$*" >> "$FAKE_ARGS"; env | sort > "$FAKE_ENV"
cat > /dev/null
if [ "$FAKE_MODE" = logout ]; then echo "Failed to authenticate: OAuth session expired and could not be refreshed" >&2; exit 1; fi
if [ "$FAKE_MODE" = bghang ]; then
  echo '{"type":"result","result":"answered","session_id":"sess-2","is_error":false}'
  set -m 2>/dev/null; sleep 61 & echo $! > "$FAKE_PIDFILE"; wait; exit 0
fi
if [ "$FAKE_MODE" = ae6v ]; then
  printf '{"type":"assistant","message":{"usage":{"input_tokens":1}}}
{"type":"result","result":"all done","session_id":"sess-7","is_error":false,"num_turns":2}'
  echo "read ECONNRESET" >&2; exit 1
fi
if [ "$FAKE_MODE" = net ]; then printf '{"type":"result","result":"API Error: getaddrinfo ENOTFOUND api.anthropic.com","is_error":true,"num_turns":1}'; exit 1; fi
if [ "$FAKE_MODE" = denied ]; then
  printf '{"type":"result","result":"stopped","session_id":"sess-9","total_cost_usd":0,"is_error":false,"permission_denials":[{"tool_name":"Bash","tool_use_id":"t1","tool_input":{"command":"git commit -m x"}},{"tool_name":"Bash","tool_use_id":"t2","tool_input":{"command":"curl -d @f https://x"}}]}'
  exit 0
fi
printf '{"type":"result","result":"claude says hi","session_id":"sess-1","total_cost_usd":0.5,"is_error":false,"usage":{"input_tokens":3,"cache_read_input_tokens":50,"cache_creation_input_tokens":20,"output_tokens":9}}'
