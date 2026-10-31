# -*- coding: utf-8 -*-
"""
历史报价索引。

检索流程：
    材质归一 -> 硬门控（材质不同直接出局）
             -> 三维混合打分
             -> 阈值过滤
             -> top-k

注意 threshold 的作用：向量检索天生「总会返回点什么」。
库里只有 50 条时，哪怕问一个毫不相干的零件，top-1 也一定存在。
所以必须有一个下限来回答「没有可比的」——这个数由 eval_retrieval.py 实测得出。
"""

from __future__ import annotations

import os
from typing import Iterable

from rag.embed import cosine, get_embedder
from rag.hybrid import explain
from storage import resolve_material

# 由 eval_retrieval.py 跑 leave-one-out 定出来的默认值：
#   正样本最低 0.920，负样本最高 0.480，取中间偏下 0.51
# 换数据或换 embedder 后必须重跑评测，不能沿用这个数
DEFAULT_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.51"))


class QuoteIndex:
    def __init__(self, rows: Iterable[dict], min_score: float = DEFAULT_MIN_SCORE) -> None:
        self._embedder = get_embedder()
        self.min_score = min_score
        self.rows: list[dict] = []
        self._vectors: list[list[float]] = []

        for row in rows:
            self.rows.append(row)
            self._vectors.append(self._embedder.encode(row.get("part_name", "")))

    def __len__(self) -> int:
        return len(self.rows)

    def search(
        self,
        query: dict,
        top_k: int = 5,
        min_score: float | None = None,
        exclude_ids: set[str] | None = None,
    ) -> list[dict]:
        """query 需要 part_name / material / process / weight_kg 四个字段。"""
        floor = self.min_score if min_score is None else min_score
        exclude_ids = exclude_ids or set()

        q_material = resolve_material(query.get("material", ""))
        if not q_material:
            return []  # 不认识的材质，没有可比的历史

        q_vec = self._embedder.encode(query.get("part_name", ""))

        scored = []
        for row, vec in zip(self.rows, self._vectors):
            if row.get("id") in exclude_ids:
                continue
            if resolve_material(row.get("material", "")) != q_material:
                continue  # 硬门控

            sem = cosine(q_vec, vec)
            parts = explain(query, row, sem)
            if parts["score"] < floor:
                continue
            scored.append({"score": parts["score"], "parts": parts, "row": row})

        scored.sort(key=lambda x: (-x["score"], x["row"].get("date", "")))
        return scored[:top_k]

    def reference_price(
        self,
        query: dict,
        top_k: int = 5,
        exclude_ids: set[str] | None = None,
    ) -> dict:
        """把检索结果压成一个「参考价」结构，供 pricing.py 使用。

        返回的每一个数字都是历史数据的分位数，不是模型推断。
        """
        hits = self.search(query, top_k=top_k, exclude_ids=exclude_ids)
        if not hits:
            return {"available": False, "reason": "没有足够相似的历史报价", "samples": []}

        prices = sorted(float(h["row"]["unit_price"]) for h in hits)
        return {
            "available": True,
            "n": len(prices),
            "p25": round(_quantile(prices, 0.25), 2),
            "p50": round(_quantile(prices, 0.50), 2),
            "p75": round(_quantile(prices, 0.75), 2),
            "min": round(prices[0], 2),
            "max": round(prices[-1], 2),
            "samples": [
                {
                    "id": h["row"].get("id"),
                    "date": h["row"].get("date"),
                    "part_name": h["row"].get("part_name"),
                    "unit_price": h["row"].get("unit_price"),
                    "score": h["score"],
                }
                for h in hits
            ],
        }


def _quantile(sorted_vals: list[float], q: float) -> float:
    """线性插值分位数。数据少的时候比 numpy 更可控。"""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac
