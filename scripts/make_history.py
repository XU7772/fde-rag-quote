# -*- coding: utf-8 -*-
"""
生成扩展版历史报价数据。

原版 history.json 只有 4 条、且没有 process 字段，导致：
  1. 检索只能按材质做精确匹配
  2. 同材质不同工艺的单价被当成可比，同比失真

这里用固定随机种子生成 50 条，保证可复现。
单价不是编的：按 pricing.py 的公式算出来，再叠加 ±3% 的历史波动。

用法：
    python scripts/make_history.py
"""

import json
import math
import random
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "backend" / "data"

PRICE_TABLE = json.loads((DATA_DIR / "price_table.json").read_text(encoding="utf-8"))
MATERIALS = PRICE_TABLE["materials"]
PROCESSES = PRICE_TABLE["processes"]

# (零件名, 材质, 工序, 单件重量范围, 数量范围)
PART_CATALOG = [
    ("不锈钢法兰盘", "304不锈钢", ["CNC车削", "去毛刺"], (0.60, 1.00), (80, 200)),
    ("不锈钢管接头", "304不锈钢", ["CNC车削"], (0.10, 0.25), (150, 400)),
    ("铝合金连接块", "6061-T6铝", ["CNC铣削", "阳极氧化"], (0.25, 0.50), (50, 150)),
    ("铝制散热片", "6061-T6铝", ["CNC铣削", "阳极氧化"], (0.15, 0.35), (200, 600)),
    ("碳钢支架", "Q235碳钢", ["激光切割", "折弯", "镀锌"], (1.00, 1.60), (200, 500)),
    ("钣金外壳", "Q235碳钢", ["激光切割", "折弯", "镀锌"], (0.80, 1.40), (100, 300)),
    ("45钢齿轮轴", "45#钢", ["CNC车削", "去毛刺"], (0.50, 0.90), (60, 180)),
    ("45钢定位销", "45#钢", ["CNC车削"], (0.05, 0.15), (300, 800)),
    ("黄铜接头", "黄铜H62", ["CNC车削"], (0.12, 0.25), (40, 120)),
    ("铜制衬套", "黄铜H62", ["CNC车削", "去毛刺"], (0.08, 0.20), (150, 400)),
]

CUSTOMERS = [
    "宏达精密机械有限公司",
    "恒立自动化设备有限公司",
    "精工传动科技有限公司",
    "中远机械制造有限公司",
    "华翔五金制品有限公司",
]

RECORDS_PER_PART = 5
SEED = 20261031


def unit_price(weight_kg: float, material_canonical: str, processes: list[str]) -> float:
    """和 pricing.py 用同一个公式，保证历史价和现价可比。"""
    material_cost = weight_kg * float(MATERIALS[material_canonical]["price_per_kg"])
    process_cost = sum(PROCESSES[p] for p in processes)
    return material_cost + process_cost


def main() -> None:
    rng = random.Random(SEED)
    rows = []

    # 每个零件生成 5 条，日期互不相同，便于做 leave-one-out 评测
    for part_name, material, processes, (w_lo, w_hi), (q_lo, q_hi) in PART_CATALOG:
        for k in range(RECORDS_PER_PART):
            month = rng.randint(1, 12)
            day = rng.randint(1, 28)
            year = 2026 if month >= 3 else 2025

            weight = round(rng.uniform(w_lo, w_hi), 2)
            quantity = rng.randint(q_lo, q_hi)

            # 历史波动 ±3%，四舍五入到 1 位小数
            drift = rng.uniform(0.97, 1.03)
            price = round(unit_price(weight, material, processes) * drift, 1)

            rows.append(
                {
                    "id": f"Q-{year}{month:02d}{day:02d}-{k + 1:02d}",
                    "date": f"{year}-{month:02d}-{day:02d}",
                    "customer": rng.choice(CUSTOMERS),
                    "part_name": part_name,
                    "material": material,
                    "process": "、".join(processes),
                    "quantity": quantity,
                    "weight_kg": weight,
                    "unit_price": price,
                    "total": round(price * quantity, 2),
                }
            )

    rows.sort(key=lambda r: (r["date"], r["id"]))

    out = DATA_DIR / "history.json"
    out.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"已写入 {out}")
    print(f"共 {len(rows)} 条，覆盖 {len(PART_CATALOG)} 种零件、{len(MATERIALS)} 种材质")
    print(f"每零件 {RECORDS_PER_PART} 条 —— 可做 leave-one-out 评测")


if __name__ == "__main__":
    main()
