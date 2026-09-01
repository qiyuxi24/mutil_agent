#!/bin/bash
set -u
H=http://127.0.0.1:8001
C=/tmp/hs.cookie
rm -f "$C"
curl -s -c "$C" -o /dev/null -X POST "$H/session/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"AgentTeams2026!"}'

echo "=== mcp-email route current ==="
curl -s -b "$C" "$H/v1/routes" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for r in d.get('data',[]):
    if 'mcp-email' in r.get('name',''):
        print(json.dumps({k:r[k] for k in ('name','domains','path','services','customConfigs') if k in r},ensure_ascii=False,indent=1))
" 2>/dev/null

B="Authorization: Bearer f917f39b709e72a84c2e34cf4782911b8c0e076b93b29e1babf7360d6a72855f"
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'
echo "=== POST default-host ==="
curl -s -m 8 -w "\nHTTP:%{http_code}\n" -X POST http://127.0.0.1:8080/mcp-servers/mcp-email -H "$B" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "$INIT" | head -c 400
echo "=== POST aigw-host ==="
curl -s -m 8 -w "\nHTTP:%{http_code}\n" -X POST http://127.0.0.1:8080/mcp-servers/mcp-email -H "Host: aigw-local.agentteams.io" -H "$B" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "$INIT" | head -c 400
echo "=== GET aigw-host (SSE handshake) ==="
curl -s -m 8 -w "\nHTTP:%{http_code}\n" http://127.0.0.1:8080/mcp-servers/mcp-email -H "Host: aigw-local.agentteams.io" -H "$B" -H "Accept: text/event-stream" | head -c 400
