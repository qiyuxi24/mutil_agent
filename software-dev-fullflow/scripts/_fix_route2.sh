#!/bin/bash
set -u
H=http://127.0.0.1:8001
C=/tmp/hs.cookie
rm -f "$C"
curl -s -c "$C" -o /dev/null -X POST "$H/session/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"AgentTeams2026!"}'

curl -s -b "$C" "$H/v1/routes" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for r in d.get('data',[]):
    if 'mcp-email' in r.get('name',''):
        r['services']=[{'name':'email-proxy.static','port':9400,'weight':100}]
        r.pop('readonly',None)
        print(json.dumps(r,ensure_ascii=False))
" > /tmp/route_email.json

echo "=== PUT /v1/routes/mcp-server-mcp-email.internal ==="
curl -s -b "$C" -w "\nHTTP:%{http_code}\n" -X PUT "$H/v1/routes/mcp-server-mcp-email.internal" \
  -H 'Content-Type: application/json' -d @/tmp/route_email.json | head -c 400
echo
echo "=== PUT /v1/routes ==="
curl -s -b "$C" -w "\nHTTP:%{http_code}\n" -X PUT "$H/v1/routes" \
  -H 'Content-Type: application/json' -d @/tmp/route_email.json | head -c 400
echo
