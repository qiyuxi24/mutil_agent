#!/bin/bash
set -u
H=http://127.0.0.1:8001
C=/tmp/hs.cookie
rm -f "$C"
curl -s -c "$C" -o /dev/null -X POST "$H/session/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"AgentTeams2026!"}'

echo "=== McpBridge list ==="
curl -s -b "$C" "$H/v1/mcpbridge" | head -c 4000
echo
echo "=== all routes names ==="
curl -s -b "$C" "$H/v1/routes" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for r in d.get('data',[]):
    print(r['name'], '|', (r.get('path') or {}).get('matchValue'), '|', [s.get('name') for s in r.get('services',[])])
" 2>/dev/null || echo "(routes parse failed)"
