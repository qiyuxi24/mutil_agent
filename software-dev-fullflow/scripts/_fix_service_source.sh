#!/bin/bash
set -u
H=http://127.0.0.1:8001
C=/tmp/hs.cookie
rm -f "$C"
curl -s -c "$C" -o /dev/null -X POST "$H/session/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"AgentTeams2026!"}'

echo "=== recreate email-proxy as static ==="
curl -s -b "$C" -w "\nHTTP:%{http_code}\n" -X POST "$H/v1/service-sources" \
  -H 'Content-Type: application/json' \
  -d '{"name":"email-proxy","type":"static","domain":"192.168.65.254:9400","port":9400,"protocol":"http"}' | head -c 600
echo
echo "=== verify ==="
curl -s -b "$C" "$H/v1/service-sources" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for s in d.get('data',[]):
    if 'email' in s.get('name',''):
        print(json.dumps(s,ensure_ascii=False)[:400])
" 2>/dev/null
