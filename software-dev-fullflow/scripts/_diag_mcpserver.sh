#!/bin/bash
set -u
H=http://127.0.0.1:8001
C=/tmp/hs.cookie
rm -f "$C"
curl -s -c "$C" -o /dev/null -X POST "$H/session/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"AgentTeams2026!"}'

for p in "/v1/mcpServer" "/v1/mcpServer?name=mcp-email" "/v1/mcpServer/list" "/v1/mcpServer/detail?mcpServerName=mcp-email"; do
  echo "=== GET $p ==="
  curl -s -b "$C" -w "\nHTTP:%{http_code}\n" "$H$p" | head -c 800
  echo
done
