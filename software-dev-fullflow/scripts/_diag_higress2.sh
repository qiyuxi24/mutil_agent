#!/bin/bash
# 批量测试 Higress MCP 网关协议形态
GW=http://127.0.0.1:8080/mcp-servers/mcp-email/mcp
B="Authorization: Bearer f917f39b709e72a84c2e34cf4782911b8c0e076b93b29e1babf7360d6a72855f"
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'

echo "=== 1. GET (default host) body ==="
curl -s -m 5 "$GW" -H "$B" | head -c 400; echo

echo "=== 2. POST + Accept: text/event-stream (default host) ==="
curl -s -m 8 -o /tmp/r2.txt -w "HTTP:%{http_code}\n" -X POST "$GW" -H "$B" -H "Content-Type: application/json" -H "Accept: text/event-stream" -d "$INIT"; head -c 400 /tmp/r2.txt; echo

echo "=== 3. POST + Accept: application/json, text/event-stream (default host) ==="
curl -s -m 8 -o /tmp/r3.txt -w "HTTP:%{http_code}\n" -X POST "$GW" -H "$B" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "$INIT"; head -c 400 /tmp/r3.txt; echo

echo "=== 4. POST initialize (aigw host, correct Bearer) ==="
curl -s -m 8 -o /tmp/r4.txt -w "HTTP:%{http_code}\n" -X POST "$GW" -H "Host: aigw-local.agentteams.io" -H "$B" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "$INIT"; head -c 400 /tmp/r4.txt; echo
