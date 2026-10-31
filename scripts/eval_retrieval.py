# -*- coding: utf-8 -*-
"""
检索质量评测 + 阈值标定。

做法是 leave-one-out：
  拿历史里的每一条记录当查询，排除它自己，看能不能召回「同一零件的其他报价」。
  ground truth 不是人工标的，是数据自带的 part_name —— 所以这个评测不需要标注成本。

输出三样东西：
  1. recall@1 / @3 / @5   —— 排序质量
  2. 正负样本的分数分布   —— 阈值该放在哪
  3. 最佳阈值（最大 F1）  —— 直接写回 RAG_MIN_SCORE

用法：
    python scripts/eval_retrieval.py
"""

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "backend"))

from rag import QuoteIndex  # noqa: E402
from rag.hybrid import split_processes  # noqa: E402

DATA = PROJECT_DIR / "backend" / "data" / "history.json"
K_VALUES = (1, 3, 5)


def as_query(row: dict) -> dict:
    return {
        "part_name": row.get("part_name", ""),
        "material": row.get("material", ""),
        "process": row.get("process", ""),
        "weight_kg": row.get("weight_kg"),
    }


def main() -> None:
    rows = json.loads(DATA.read_text(encoding="utf-8"))
    index = QuoteIndex(rows, min_score=0.0)  # 评测时不过滤，先看裸排序

    print(f"数据：{len(rows)} 条历史报价")
    print(f"embedder：{index._embedder.name}\n")

    # ---------- 1. recall@k ----------
    hits_at = {k: 0 for k in K_VALUES}
    valid_queries = 0
    pairs: list[tuple[float, bool]] = []  # (score, 是否同一零件)

    for row in rows:
        truth = row["part_name"]
        ranked = index.search(as_query(row), top_k=len(rows), exclude_ids={row["id"]})
        positives = [r for r in rows if r["part_name"] == truth]

        if not positives:
            continue
        valid_queries += 1

        for k in K_VALUES:
            top = ranked[:k]
            if any(h["row"]["part_name"] == truth for h in top):
                hits_at[k] += 1

        for h in ranked:
            pairs.append((h["score"], h["row"]["part_name"] == truth))

    print("=== 排序质量 ===")
    for k in K_VALUES:
        print(f"  recall@{k} = {hits_at[k] / valid_queries:.3f}  ({hits_at[k]}/{valid_queries})")

    # ---------- 2. 分数分布 ----------
    pos = sorted(s for s, ok in pairs if ok)
    neg = sorted(s for s, ok in pairs if not ok)

    def pct(vals: list[float], q: float) -> float:
        if not vals:
            return 0.0
        i = min(int(len(vals) * q), len(vals) - 1)
        return vals[i]

    print("\n=== 分数分布 ===")
    print(f"  正样本（同一零件） n={len(pos):<3} "
          f"p5={pct(pos, 0.05):.3f} p50={pct(pos, 0.50):.3f} p95={pct(pos, 0.95):.3f}")
    print(f"  负样本（不同零件） n={len(neg):<3} "
          f"p5={pct(neg, 0.05):.3f} p50={pct(neg, 0.50):.3f} p95={pct(neg, 0.95):.3f}")

    # ---------- 3. 阈值扫描 ----------
    best = {"t": 0.0, "f1": -1.0, "p": 0.0, "r": 0.0}
    for i in range(0, 101):
        t = i / 100
        tp = sum(1 for s, ok in pairs if s >= t and ok)
        fp = sum(1 for s, ok in pairs if s >= t and not ok)
        fn = len(pos) - tp
        if tp == 0:
            continue
        p = tp / (tp + fp)
        r = tp / (tp + fn)
        f1 = 2 * p * r / (p + r)
        if f1 > best["f1"]:
            best = {"t": t, "f1": f1, "p": p, "r": r}

    print("\n=== 最佳阈值 ===")
    print(f"  RAG_MIN_SCORE = {best['t']:.2f}")
    print(f"  precision = {best['p']:.3f}  recall = {best['r']:.3f}  F1 = {best['f1']:.3f}")

    # 门槛之上还剩多少查询能召回
    surviving = 0
    for row in rows:
        ranked = index.search(as_query(row), top_k=3, exclude_ids={row["id"]},
                              min_score=best["t"])
        if any(h["row"]["part_name"] == row["part_name"] for h in ranked):
            surviving += 1
    print(f"  阈值 {best['t']:.2f} 下 recall@3 = {surviving / valid_queries:.3f} "
          f"({surviving}/{valid_queries})")

    print(f"\n把这一行写进 .env 或直接改 rag/index.py 的默认值：")
    print(f"  RAG_MIN_SCORE={best['t']:.2f}")


if __name__ == "__main__":
    main()
