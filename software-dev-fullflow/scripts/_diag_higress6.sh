#!/bin/bash
set -u
H=http://127.0.0.1:8001
C=/tmp/hs.cookie
rm -f "$C"
curl -s -c "$C" -o /dev/null -X POST "$H/session/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"AgentTeams2026!"}'

echo "=== services (email/host-tools/code-scan related) ==="
curl -s -b "$C" "$H/v1/services" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for s in d.get('data',[]):
    n=s.get('name','')
    if any(k in n for k in ('email','host-tools','code-scan','proxy')):
        print(json.dumps(s,ensure_ascii=False)[:600])
        print('---')
" 2>/dev/null || echo "(services parse failed)"
echo "=== full route: mcp-server-mcp-email.internal ==="
curl -s -b "$C" "$H/v1/routes" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for r in d.get('data',[]):
    if 'mcp-email' in r.get('name',''):
        print(json.dumps(r,ensure_ascii=False,indent=1))
" 2>/dev/null || echo "(route parse failed)"
