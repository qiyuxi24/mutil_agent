"""workers.yaml 解析 —— AgentTeams Worker CRD 的单一数据源。

从 workers.yaml 读取每个 Worker 的 skills / mcpServers / model / runtime，
避免 Python 代码中硬编码重复的列表。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# workers.yaml 的默认路径（相对于 src/agentteams/）
_workers_yaml_path: str | None = None
_workers_yaml_cache: dict[str, dict[str, Any]] | None = None

# 解析失败时的硬编码兜底（与 workers.yaml 保持一致）
DEFAULT_WORKER_SKILLS: dict[str, list[str]] = {
    "aggregator": ["issue-parsing", "knowledge-rag", "evidence-log"],
    "rootcause": ["root-cause-analysis", "impact-analysis", "git-operations",
                  "repo-context", "code-search", "knowledge-rag", "evidence-log"],
    "fixer": ["code-gen", "git-operations", "repo-context", "code-search", "evidence-log"],
    "tester": ["test-generation", "evidence-log"],
    "releaser": ["release-gate", "evidence-log"],
    "retrospector": ["retrospective", "knowledge-rag", "evidence-log"],
}

DEFAULT_WORKER_MCP: dict[str, list[str]] = {
    "aggregator": ["github"],
    "rootcause": ["github"],
    "fixer": ["github", "code-scan"],
    "tester": ["test-platform"],
    "releaser": ["ci"],
    "retrospector": [],
}


def set_workers_yaml_path(path: str) -> None:
    """覆盖 workers.yaml 的路径（便于测试/自定义部署）。"""
    global _workers_yaml_path, _workers_yaml_cache
    _workers_yaml_path = path
    _workers_yaml_cache = None


def get_workers_yaml_path() -> Path:
    """获取 workers.yaml 的绝对路径。"""
    if _workers_yaml_path:
        return Path(_workers_yaml_path)
    return Path(__file__).resolve().parent.parent / "agentteams" / "workers.yaml"


def clear_cache() -> None:
    """清除解析缓存（在 apply 更新后调用）。"""
    global _workers_yaml_cache
    _workers_yaml_cache = None


def parse_workers_yaml() -> dict[str, dict[str, Any]]:
    """解析 workers.yaml，返回 {worker_name: {skills, mcpServers, model, runtime}}。

    使用轻量逐行解析（不引入 PyYAML 依赖），支持多文档（--- 分隔）。
    """
    global _workers_yaml_cache
    if _workers_yaml_cache is not None:
        return _workers_yaml_cache

    yaml_path = get_workers_yaml_path()
    if not yaml_path.exists():
        return {}

    text = yaml_path.read_text(encoding="utf-8")
    workers: dict[str, dict[str, Any]] = {}
    current_worker: dict[str, Any] | None = None
    current_section: str = ""

    for line in text.split("\n"):
        stripped = line.strip()

        # 检测新 Worker 文档（--- 分隔符 或 metadata/name）
        if stripped == "---":
            if current_worker and "name" in current_worker:
                workers[current_worker["name"]] = current_worker
            current_worker = None
            current_section = ""
            continue

        if not current_worker and stripped.startswith("metadata:"):
            current_worker = {}
            current_section = "metadata"
            continue

        if current_worker is not None and stripped.startswith("spec:"):
            current_section = "spec"
            continue

        # metadata.name
        if current_section == "metadata" and stripped.startswith("name:"):
            current_worker["name"] = stripped.split(":", 1)[1].strip()
            continue

        # spec 下的字段
        if current_section == "spec":
            if stripped.startswith("model:"):
                current_worker["model"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("runtime:"):
                current_worker["runtime"] = stripped.split(":", 1)[1].strip()
            elif stripped == "skills:":
                current_worker["skills"] = []
            elif stripped == "mcpServers:":
                current_worker["mcpServers"] = []
            elif stripped.startswith("- ") and "skills" in current_worker and isinstance(current_worker.get("skills"), list):
                current_worker["skills"].append(stripped[2:].strip())
            elif stripped.startswith("- ") and "mcpServers" in current_worker and isinstance(current_worker.get("mcpServers"), list):
                current_worker["mcpServers"].append(stripped[2:].strip())

    # 处理最后一个 Worker
    if current_worker and "name" in current_worker:
        workers[current_worker["name"]] = current_worker

    _workers_yaml_cache = workers
    return workers


def get_worker_skills(name: str) -> list[str]:
    """获取 Worker 的 skills 列表（优先 workers.yaml，失败回退硬编码默认值）。"""
    workers = parse_workers_yaml()
    if name in workers:
        return workers[name].get("skills", [])
    return DEFAULT_WORKER_SKILLS.get(name, [])


def get_worker_mcp(name: str) -> list[str]:
    """获取 Worker 的 MCP 服务器列表（优先 workers.yaml，失败回退硬编码默认值）。"""
    workers = parse_workers_yaml()
    if name in workers:
        return workers[name].get("mcpServers", [])
    return DEFAULT_WORKER_MCP.get(name, [])
