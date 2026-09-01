#!/bin/bash
echo "=== POST /mcp-servers/mcp-email (no /mcp suffix, aigw host + Bearer) ==="
curl -s -m 8 -w "\nHTTP:%{http_code}\n" -X POST http://127.0.0.1:8080/mcp-servers/mcp-email \
  -H "Host: aigw-local.agentteams.io" \
  -H "Authorization: Bearer f917f39b709e72a84c2e34cf4782911b8c0e076b93b29e1babf7360d6a72855f" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 1200
echo
echo "=== POST /mcp-servers/mcp-email (default host, no auth) ==="
curl -s -m 8 -w "\nHTTP:%{http_code}\n" -X POST http://127.0.0.1:8080/mcp-servers/mcp-email \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 500
echo
