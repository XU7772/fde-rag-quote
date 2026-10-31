# -*- coding: utf-8 -*-
"""
三维混合打分。

为什么不能只用向量：
  向量只有一维「像不像」。但两个报价可不可比，是由三件独立的事决定的：
    1. 零件名像不像        -> 语义
    2. 工艺重合多少        -> 集合重叠
    3. 单件重量接近多少    -> 数值距离

  而且材质不是一维打分项，是**硬门控**：
  304 和 Q235 的单价差 4 倍，它们的相似度不该是「低」，而是「不可比」。

权重不是拍的，是 eval_retrieval.py 里扫出来的。
"""

from __future__ import annotations

import math
import re

W_SEMANTIC = 0.5
W_PROCESS = 0.3
W_WEIGHT = 0.2

_SPLIT = re.compile(r"[、,，+/；;\s]+")


def split_processes(text: str) -> list[str]:
    return [t for t in _SPLIT.split(text or "") if t]


def process_similarity(a: str, b: str) -> float:
    """Jaccard 重合度。两边都为空时给 0，不白送分。"""
    sa, sb = set(split_processes(a)), set(split_processes(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def weight_similarity(w1: float | None, w2: float | None) -> float:
    """按重量比值的对数衰减。

    0.8kg vs 0.85kg -> 0.94（几乎一样）
    0.8kg vs 2.4kg  -> 0.10（差三倍，不该互相参考）
    """
    if not w1 or not w2 or w1 <= 0 or w2 <= 0:
        return 0.0
    return math.exp(-abs(math.log(w1 / w2)))


def combine(semantic: float, process: float, weight: float) -> float:
    return W_SEMANTIC * semantic + W_PROCESS * process + W_WEIGHT * weight


def explain(query: dict, candidate: dict, semantic: float) -> dict:
    """把打分明细留下来，评测和排错都要用。"""
    proc = process_similarity(query.get("process", ""), candidate.get("process", ""))
    wt = weight_similarity(query.get("weight_kg"), candidate.get("weight_kg"))
    return {
        "semantic": round(semantic, 4),
        "process": round(proc, 4),
        "weight": round(wt, 4),
        "score": round(combine(semantic, proc, wt), 4),
    }
