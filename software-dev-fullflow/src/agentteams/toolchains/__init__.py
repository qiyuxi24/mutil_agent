# -*- coding: utf-8 -*-
"""
toolchains —— 团队自建工具链（AgentScope 实现，确定性 REST API）

用阿里官方 AgentScope 2.x 的 FunctionTool 把团队确定性工具链（代码扫描 / 测试平台）
定义成 MCP 工具，并通过 FastAPI 暴露为 REST 端点，供 Higress 网关 setup-mcp-server.sh
注册为 AgentTeams 平台的 MCP Server，让 Worker（fixer/tester）通过 mcporter 真实调用。

目录结构：
  core.py                 共享确定性内核（复用 check-patch-integrity / verify_test_gate 逻辑）
  code_scan_service.py    代码扫描服务（start_scan / get_scan_result / list_open_issues / get_issue_detail）
  test_platform_service.py 测试平台服务（run_tests / get_test_result / get_coverage / run_static_analysis）

接入链路（对齐 design/MCP-INTEGRATION.md）：
  1. 本机启动服务：  python -m src.agentteams.toolchains.code_scan_service   （FastAPI，默认 0.0.0.0:9100/9200）
  2. 生成 YAML：      scripts/register-toolchains.ps1 -GenerateYaml
  3. 注册到 Higress： scripts/register-toolchains.ps1 -RegisterAll   （调官方 setup-mcp-server.sh）
  4. Worker 调用：    docker exec agentteams-worker-fixer mcporter list code-scan --schema
"""
