"""Token 估算（字符级，无外部依赖）。

提供确定性 token 估算，用于上下文预算判断（不依赖 LLM 自评）。
精度约 ±15%，生产环境可替换为 tiktoken。
"""

from __future__ import annotations


class TokenEstimator:
    """简单 token 估算器：英文 ~4 chars/token，中文 ~1.5 chars/token。"""

    # 经验值：英文每 token 约 4 字符，中文每 token 约 1.5 字符
    EN_CHARS_PER_TOKEN = 4.0
    ZH_CHARS_PER_TOKEN = 1.5

    @staticmethod
    def estimate(text: str) -> int:
        """估算文本的 token 数。"""
        if not text:
            return 0
        zh_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        en_count = len(text) - zh_count
        return int(zh_count / TokenEstimator.ZH_CHARS_PER_TOKEN +
                   en_count / TokenEstimator.EN_CHARS_PER_TOKEN)

    @staticmethod
    def estimate_messages(messages: list[dict[str, str]]) -> int:
        """估算消息列表的总 token 数。"""
        return sum(TokenEstimator.estimate(m.get("content", "")) for m in messages)
