#!/bin/bash
set -u
H=http://127.0.0.1:8001
C=/tmp/hs.cookie
rm -f "$C"
curl -s -c "$C" -o /dev/null -X POST "$H/session/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"AgentTeams2026!"}'

echo "=== routes (grep mcp) ==="
curl -s -b "$C" "$H/v1/routes" | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d,indent=1,ensure_ascii=False)[:2000])" 2>/dev/null || curl -s -b "$C" "$H/v1/routes" | head -c 1500
echo
echo "=== config dump: files containing mcp-email ==="
grep -rln 'mcp-email' /var/lib /etc/higress /root 2>/dev/null | head -10
echo "=== config dump: files containing mcpbridge/mcpServer (case-insensitive) ==="
grep -rlniE 'mcpbridge|mcpserver' /var/lib /etc/higress 2>/dev/null | head -10
echo "=== envoy listeners/routes sample ==="
ls /var/lib/higress 2>/dev/null | head
