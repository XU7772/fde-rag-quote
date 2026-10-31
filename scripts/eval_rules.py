# -*- coding: utf-8 -*-
"""
规则引擎评测。

20 个构造用例，每个都明确写了「应该触发哪些规则」。
评测三件事：
  1. 拦截率   —— 该触发的有没有触发（recall）
  2. 误杀率   —— 不该触发的有没有误触发（1 - precision）
  3. 预筛等价 —— select_rules 粗筛后的结果，必须和全量扫描完全一致

第 3 点是关键：它证明「用 RAG 筛规则」这个优化是安全的，
不会因为省了几次比较而漏掉一条该报的错。

用法：
    python scripts/eval_rules.py
"""

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "backend"))

from rules import check, parse_rules, select_rules  # noqa: E402


def item(part, material, process, weight=0.8, qty=100, days=7):
    return {
        "part_name": part,
        "material": material,
        "process": process,
        "weight_kg": weight,
        "quantity": qty,
        "unit": "件",
        "delivery_days": days,
    }


def order(urgent=False):
    return {"customer": "测试客户", "inquiry_no": "T-001", "date": "2026-10-31", "urgent": urgent}


# (用例名, 零件, 订单, 单件价, 期望触发的规则)
CASES = [
    ("R01 304镀锌",
     item("法兰盘", "304不锈钢", "CNC车削、镀锌"), order(), None, {"R01"}),
    ("R01 别名SUS304",
     item("法兰盘", "SUS304", "CNC车削、镀锌"), order(), None, {"R01"}),
    ("R02 阳极氧化缺去毛刺",
     item("连接块", "6061-T6铝", "CNC铣削、阳极氧化"), order(), None, {"R02"}),
    ("R03 铝件镀锌",
     item("连接块", "6061-T6铝", "CNC铣削、镀锌"), order(), None, {"R03"}),
    ("R04 碳钢无表面处理",
     item("支架", "Q235碳钢", "激光切割、折弯"), order(), None, {"R04", "R09"}),
    ("R05 45钢无防锈",
     item("齿轮轴", "45#钢", "CNC车削"), order(), None, {"R05"}),
    ("R06 急单交期2天",
     item("法兰盘", "304不锈钢", "CNC车削、去毛刺", days=2), order(True), None, {"R06"}),
    ("R07 黄铜阳极氧化",
     item("接头", "黄铜H62", "CNC车削、去毛刺、阳极氧化", weight=0.18), order(), None, {"R07"}),
    ("R08 重件",
     item("压板", "304不锈钢", "CNC车削、去毛刺", weight=2.5), order(), None, {"R08"}),
    ("R09 激光切割缺去毛刺",
     item("面板", "304不锈钢", "激光切割", weight=0.5), order(), None, {"R09"}),
    ("R10 小批量",
     item("销子", "304不锈钢", "CNC车削、去毛刺", qty=5), order(), None, {"R10"}),
    ("R11 高单价",
     item("法兰盘", "304不锈钢", "CNC车削、去毛刺"), order(), 600.0, {"R11"}),
    ("干净单子",
     item("法兰盘", "304不锈钢", "CNC车削、去毛刺"), order(), None, set()),
    ("碳钢镀锌且去毛刺",
     item("支架", "Q235碳钢", "激光切割、折弯、去毛刺、镀锌"), order(), None, set()),
    ("45钢已镀锌",
     item("齿轮轴", "45#钢", "CNC车削、去毛刺、镀锌"), order(), None, set()),
    ("铝件已去毛刺",
     item("连接块", "6061-T6铝", "CNC铣削、去毛刺、阳极氧化"), order(), None, set()),
    ("急单但交期5天",
     item("法兰盘", "304不锈钢", "CNC车削、去毛刺", days=5), order(True), None, set()),
    ("重量1.9未超限",
     item("压板", "304不锈钢", "CNC车削、去毛刺", weight=1.9), order(), None, set()),
    ("数量刚好10",
     item("销子", "304不锈钢", "CNC车削、去毛刺", qty=10), order(), None, set()),
    ("单价刚好500",
     item("法兰盘", "304不锈钢", "CNC车削、去毛刺"), order(), 500.0, set()),
]


def main() -> None:
    rules = parse_rules()
    print(f"规则库：{len(rules)} 条 —— {', '.join(r.id for r in rules)}\n")

    tp = fp = fn = 0
    mismatch = []
    select_mismatch = []

    print(f"{'用例':<24}{'期望':<16}{'实际':<16}{'结果'}")
    print("-" * 72)

    for name, it, od, price, expect in CASES:
        actual = {v.rule_id for v in check([it], od, [price], rules)}

        missing = expect - actual
        extra = actual - expect
        tp += len(expect & actual)
        fn += len(missing)
        fp += len(extra)
        ok = not missing and not extra
        if not ok:
            mismatch.append((name, sorted(expect), sorted(actual)))

        # 预筛等价性
        selected = select_rules([it], od, rules)
        sel_actual = {v.rule_id for v in check([it], od, [price], selected)}
        if sel_actual != actual:
            select_mismatch.append((name, sorted(actual - sel_actual)))

        mark = "OK" if ok else f"缺{','.join(sorted(missing)) or '-'} 多{','.join(sorted(extra)) or '-'}"
        print(f"{name:<24}{','.join(sorted(expect)) or '—':<16}"
              f"{','.join(sorted(actual)) or '—':<16}{mark}")

    recall = tp / (tp + fn) if (tp + fn) else 1.0
    precision = tp / (tp + fp) if (tp + fp) else 1.0

    print("\n=== 结果 ===")
    print(f"  用例数        : {len(CASES)}")
    print(f"  拦截率 recall : {recall:.3f}  ({tp} 命中 / {tp + fn} 应命中)")
    print(f"  精确率 precision: {precision:.3f}")
    print(f"  误杀          : {fp} 条")
    print(f"  预筛等价      : {'全部一致' if not select_mismatch else '不一致 ' + str(select_mismatch)}")

    if mismatch:
        print("\n  不符合预期的用例：")
        for name, e, a in mismatch:
            print(f"    - {name}: 期望 {e} 实际 {a}")

    raise SystemExit(0 if not mismatch and not select_mismatch else 1)


if __name__ == "__main__":
    main()
