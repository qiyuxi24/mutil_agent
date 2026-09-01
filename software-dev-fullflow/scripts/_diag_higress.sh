#!/bin/bash
# 诊断 Higress MCP 配置（临时脚本，用完即删）
set -u
H=http://127.0.0.1:8001
C=/tmp/hs.cookie
rm -f "$C"
curl -s -c "$C" -o /dev/null -X POST "$H/session/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"AgentTeams2026!"}'
echo "=== consumers ==="
curl -s -b "$C" "$H/v1/consumers" | head -c 4000
echo
echo "=== mcpServer list ==="
curl -s -b "$C" "$H/v1/mcpServer/list" | head -c 3000
echo
echo "=== mcp-email detail ==="
curl -s -b "$C" "$H/v1/mcpServer/detail?mcpServerName=mcp-email" | head -c 4000
echo
