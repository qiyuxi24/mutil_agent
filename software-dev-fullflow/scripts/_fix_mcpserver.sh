#!/bin/bash
set -u
H=http://127.0.0.1:8001
C=/tmp/hs.cookie
rm -f "$C"
curl -s -c "$C" -o /dev/null -X POST "$H/session/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"AgentTeams2026!"}'

echo "=== PUT /v1/mcpServer (services -> email-proxy.static) ==="
curl -s -b "$C" -w "\nHTTP:%{http_code}\n" -X PUT "$H/v1/mcpServer" \
  -H 'Content-Type: application/json' \
  -d '{"name":"mcp-email","description":"mcp-email MCP Proxy Server (http)","domains":["aigw-local.agentteams.io"],"services":[{"name":"email-proxy.static","port":9400,"weight":100}],"type":"OPEN_API"}' | head -c 600
echo
echo "=== wait for envoy reload, then test ==="
sleep 8
curl -s -m 8 -w "\nHTTP:%{http_code}\n" -X POST http://127.0.0.1:8080/mcp-servers/mcp-email \
  -H "Host: aigw-local.agentteams.io" \
  -H "Authorization: Bearer f917f39b709e72a84c2e34cf4782911b8c0e076b93b29e1babf7360d6a72855f" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 1000
echo
