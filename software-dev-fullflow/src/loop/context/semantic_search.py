"""语义记忆检索 —— 升级长期记忆的搜索方式。

从子串匹配升级为语义搜索：
  - 优先用 embedding API（DeepSeek），降级为 TF-IDF
  - 支持多类别并行搜索
  - 搜索结果带相关度排序
"""

from __future__ import annotations

import json
import os
from typing import Any

from .memory_tiers import LongTermMemory


class SemanticMemorySearch:
    """语义记忆检索（作用于 LongTermMemory）。"""

    def __init__(self, long_mem: LongTermMemory):
        self._long_mem = long_mem
        self._use_embedding = False  # 是否启用 embedding（需 API）

    # ---- TF-IDF 降级实现 ----

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """简单分词：英文按空格/标点，中文按字。"""
        import re
        tokens = []
        # 英文词（2个字符以上）
        for m in re.finditer(r'[a-zA-Z]{2,}', text.lower()):
            tokens.append(m.group())
        # 中文字
        for ch in text:
            if '\u4e00' <= ch <= '\u9fff':
                tokens.append(ch)
        return tokens

    @staticmethod
    def _tf_idf_score(query: str, document: str, corpus_docs: list[str]) -> float:
        """计算 query 与 document 的 TF-IDF 相似度。"""
        import math
        query_tokens = set(SemanticMemorySearch._tokenize(query))
        if not query_tokens:
            return 0.0

        doc_tokens = SemanticMemorySearch._tokenize(document)
        if not doc_tokens:
            return 0.0

        N = len(corpus_docs) + 1  # +1 避免除零

        score = 0.0
        for qt in query_tokens:
            tf = doc_tokens.count(qt) / len(doc_tokens) if doc_tokens else 0
            df = sum(1 for d in corpus_docs if qt in SemanticMemorySearch._tokenize(d))
            idf = math.log((N + 1) / (df + 1)) + 1.0
            score += tf * idf

        return score

    # ---- 搜索 ----

    def search_tfidf(self, query: str, category: str = "lessons",
                     top_k: int = 5) -> list[dict[str, Any]]:
        """TF-IDF 语义搜索（降级方案）。"""
        entries = self._long_mem.entries().get(category, [])
        if not entries:
            return []

        corpus = [json.dumps(e, ensure_ascii=False) for e in entries]

        scored = []
        for i, entry in enumerate(entries):
            doc_text = corpus[i]
            substring_match = query.lower() in doc_text.lower()
            tfidf = self._tf_idf_score(query, doc_text, corpus)
            score = tfidf + (0.3 if substring_match else 0.0)
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    async def search_embedding(self, query: str, category: str = "lessons",
                               top_k: int = 5) -> list[dict[str, Any]]:
        """Embedding 语义搜索（优先方案，需 DeepSeek API）。

        实际未真正实现 embedding 缓存，统一降级为 TF-IDF。
        """
        entries = self._long_mem.entries().get(category, [])
        if not entries:
            return []

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            return self.search_tfidf(query, category, top_k)

        try:
            import httpx
            async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
                resp = await client.post(
                    "https://api.deepseek.com/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"input": query, "model": "deepseek-embedding"},
                )
                if resp.status_code != 200:
                    return self.search_tfidf(query, category, top_k)
                data = resp.json()
                # 仅验证 API 可用；实际检索仍需缓存所有 memory 的 embedding，
                # 这里统一降级为 TF-IDF。
                _ = data["data"][0]["embedding"]
            return self.search_tfidf(query, category, top_k)
        except Exception:
            return self.search_tfidf(query, category, top_k)

    async def search(self, query: str, category: str = "lessons",
                     top_k: int = 5, prefer_embedding: bool = True) -> list[dict[str, Any]]:
        """语义搜索入口。

        优先使用 embedding，降级为 TF-IDF，再降级为子串匹配。
        """
        if prefer_embedding and self._use_embedding:
            results = await self.search_embedding(query, category, top_k)
            if results:
                return results

        results = self.search_tfidf(query, category, top_k)
        if results:
            return results

        # 最终降级：原始子串匹配
        return self._long_mem.search(category, query, top_k)

    def search_multi_category(self, query: str, categories: list[str] | None = None,
                              top_k: int = 5) -> dict[str, list[dict[str, Any]]]:
        """多类别并行搜索。"""
        categories = categories or self._long_mem.CATEGORIES
        results = {}
        for cat in categories:
            results[cat] = self.search_tfidf(query, cat, top_k)
        return results
