#!/bin/bash
set -u
H=http://127.0.0.1:8001
C=/tmp/hs.cookie
rm -f "$C"
curl -s -c "$C" -o /dev/null -X POST "$H/session/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"AgentTeams2026!"}'

echo "=== version files ==="
ls /var/lib/higress 2>/dev/null
cat /var/lib/higress/version 2>/dev/null
higress --version 2>/dev/null
echo
echo "=== global plugins ==="
curl -s -b "$C" "$H/v1/global-plugins" | head -c 2000
echo
echo "=== plugins (all) ==="
curl -s -b "$C" "$H/v1/plugins" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    for p in d.get('data',[]):
        print(p.get('name'), '| enabled:', p.get('enable'), '| scope:', p.get('scope',{}).get('type'))
except Exception as e:
    print('parse-fail', e)
" 2>/dev/null | head -30
