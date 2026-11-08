#!/bin/sh
[ "$1" = export ] && { echo '{"info":{"id":"'"$2"'"},"messages":[]}'; exit 0; }
echo "$*" >> "$FAKE_ARGS"; env | sort > "$FAKE_ENV"; cat > "$FAKE_ARGS.brief"
echo '{"type":"step_start","sessionID":"ses_1","part":{"type":"step-start"}}'
case "$FAKE_MODE" in
  limit) echo '{"type":"error","sessionID":"ses_1","error":{"name":"APIError","data":{"message":"You have hit your usage limit, try again at 5:50 AM"}}}'; exit 1;;
  silent) exit 1;;
  secret) echo '{"type":"tool_use","sessionID":"ses_1","part":{"type":"tool","tool":"bash","state":{"status":"completed","input":{"command":"cat ~/.ssh/id_ed25519"},"output":"cat: Operation not permitted"}}}'
          sleep 30;;
esac
echo '{"type":"text","sessionID":"ses_1","part":{"type":"text","text":"grok did it"}}'
echo '{"type":"step_finish","sessionID":"ses_1","part":{"type":"step-finish","cost":0.25,"tokens":{"input":10,"output":3,"reasoning":2,"cache":{"read":40,"write":0}}}}'
