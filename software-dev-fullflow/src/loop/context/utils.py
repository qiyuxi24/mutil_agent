"""便捷工具函数 —— 兼容 PLAN.md ctx-1 的四个函数签名。"""

from __future__ import annotations

from pathlib import Path

from .budget import ContextBudget
from .estimator import TokenEstimator


def trim_context(text: str, max_tokens: int, preserve_head_ratio: float = 0.7) -> str:
    """智能截断：保留头尾关键信息，去掉中间。

    Args:
        text: 要截断的文本
        max_tokens: 最大 token 数
        preserve_head_ratio: 头部保留比例（0.0~1.0）
    """
    budget = ContextBudget(total_budget=max_tokens)
    return budget._truncate_to_fit(text, max_tokens)


def compact_history(messages: list[dict[str, str]], max_tokens: int) -> str:
    """压缩长历史为摘要。

    简化实现：保留最近消息，旧消息走 truncate。
    生产环境可替换为 LLM 摘要。
    """
    if not messages:
        return ""
    total = TokenEstimator.estimate_messages(messages)
    if total <= max_tokens:
        return "\n".join(m.get("content", "") for m in messages)

    # 保留最近消息（从尾部开始）
    kept = []
    used = 0
    for m in reversed(messages):
        content = m.get("content", "")
        tokens = TokenEstimator.estimate(content)
        if used + tokens > max_tokens:
            break
        kept.insert(0, content)
        used += tokens
    return "\n".join(kept)


def budget_allocate(total_budget: int, parts: dict[str, int]) -> dict[str, int]:
    """按比例分配 token 预算。

    Args:
        total_budget: 总预算
        parts: {名称: 比例}，比例之和应为 1.0

    Returns:
        {名称: 分配的 token 数}
    """
    return {name: int(total_budget * ratio) for name, ratio in parts.items()}


def offload_to_file(content: str, filepath: Path) -> str:
    """写入外部文件，返回引用路径。

    Returns:
        "[offloaded: {filename}] {preview}"
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    preview = content[:100].replace("\n", " ")
    return f"[offloaded: {filepath.name}] {preview}..."
