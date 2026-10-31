# -*- coding: utf-8 -*-
"""
确定性计价。

这一段全程零 LLM：同样的输入一定得到同样的输出。
单价 = 单件重量 × 材料单价 + 各道工序费之和
订单 = Σ行小计 + 开机费，急单再乘系数。

RAG 在这里的作用被限定为「只读旁证」：
  - 检索相似历史报价，算出参考区间 p25/p50/p75 和偏离度
  - 检索工艺规则，产出校验结论
两者都不参与 total 的计算。报价公式没变，一个数都没动。
"""

import re

from rag import get_index
from rules import check as check_rules, has_blocking
from storage import (
    PRICE_TABLE,
    last_same_material,
    resolve_material,
    archive_quote,
    new_quote_id,
)

MATERIALS = PRICE_TABLE.get("materials", {})
PROCESSES: dict[str, float] = PRICE_TABLE.get("processes", {})
SETUP_FEE = float(PRICE_TABLE.get("setup_fee", 0))
EXPEDITE = float(PRICE_TABLE.get("expedite_multiplier", 1.0))


def split_processes(text: str) -> list[str]:
    return [t for t in re.split(r"[、,，+/；;\s]+", text or "") if t]


def match_process(token: str) -> str | None:
    """把「CNC车削」这类写法匹配到价格表里的工序名。"""
    if token in PROCESSES:
        return token
    for name in PROCESSES:
        if token in name or name in token:
            return name
    return None


def calculate_quote(order, items, archive: bool = True) -> dict:
    line_items = []
    total_quantity = 0.0

    for item in items:
        canonical = resolve_material(item.material)
        if not canonical:
            known = "、".join(MATERIALS.keys())
            raise ValueError(f"不认识的材质「{item.material}」。价格表里只有：{known}")

        if item.weight_kg is None or item.weight_kg <= 0:
            raise ValueError(f"「{item.part_name}」缺少单件重量，无法计算材料费")

        material = MATERIALS[canonical]
        material_cost = round(item.weight_kg * float(material["price_per_kg"]), 2)

        matched, unknown = [], []
        for token in split_processes(item.process):
            name = match_process(token)
            if name:
                matched.append(name)
            else:
                unknown.append(token)
        process_cost = round(sum(PROCESSES[name] for name in matched), 2)

        unit_price = round(material_cost + process_cost, 2)
        line_total = round(unit_price * item.quantity, 2)
        total_quantity += item.quantity

        previous = last_same_material(canonical)
        change_pct = None
        if previous and previous.get("unit_price"):
            change_pct = round(
                (unit_price - float(previous["unit_price"]))
                / float(previous["unit_price"])
                * 100,
                1,
            )

        # --- 新增：相似历史检索（只读旁证，不参与计价） ---
        reference = get_index().reference_price(
            {
                "part_name": item.part_name,
                "material": canonical,
                "process": item.process,
                "weight_kg": item.weight_kg,
            },
            top_k=5,
        )
        deviation_pct = None
        if reference["available"] and reference["p50"]:
            deviation_pct = round(
                (unit_price - reference["p50"]) / reference["p50"] * 100, 1
            )

        line_items.append(
            {
                "part_name": item.part_name,
                "material": canonical,
                "material_input": item.material,
                "weight_kg": item.weight_kg,
                "quantity": item.quantity,
                "unit": item.unit,
                "process": item.process,
                "processes": matched,
                "unknown_processes": unknown,
                "delivery_days": item.delivery_days,
                "material_price_per_kg": material["price_per_kg"],
                "material_cost": material_cost,
                "process_cost": process_cost,
                "unit_price": unit_price,
                "line_total": line_total,
                "previous": (
                    {
                        "date": previous["date"],
                        "unit_price": previous["unit_price"],
                        "part_name": previous.get("part_name"),
                        "id": previous.get("id"),
                    }
                    if previous
                    else None
                ),
                "change_pct": change_pct,
                "reference": reference,
                "deviation_pct": deviation_pct,
            }
        )

    has_cnc = any(
        any("CNC" in name for name in row["processes"]) for row in line_items
    )
    setup_fee = round(SETUP_FEE if has_cnc else 0.0, 2)
    subtotal = round(sum(row["line_total"] for row in line_items) + setup_fee, 2)
    multiplier = EXPEDITE if order.urgent else 1.0
    total = round(subtotal * multiplier, 2)

    compared = [row for row in line_items if row["change_pct"] is not None]
    biggest = max(compared, key=lambda row: abs(row["change_pct"])) if compared else None

    # --- 新增：工艺规则校验（纯代码判断，无 LLM） ---
    violations = check_rules(items, order, [row["unit_price"] for row in line_items])
    violation_dicts = [v.as_dict() for v in violations]
    blocking = [v for v in violations if v.level == "error"]

    result = {
        "quote_id": new_quote_id(),
        "line_items": line_items,
        "item_count": len(line_items),
        "total_quantity": total_quantity,
        "setup_fee": setup_fee,
        "expedite": bool(order.urgent),
        "expedite_multiplier": multiplier,
        "subtotal": subtotal,
        "total": total,
        "currency": "CNY",
        "violations": violation_dicts,
        "blocked": bool(blocking),
        "biggest_change": (
            {
                "part_name": biggest["part_name"],
                "material": biggest["material"],
                "change_pct": biggest["change_pct"],
                "previous_unit_price": (
                    biggest["previous"]["unit_price"] if biggest["previous"] else None
                ),
                "unit_price": biggest["unit_price"],
            }
            if biggest
            else None
        ),
    }

    # 给 LLM 写 summary 用的事实包：只有数字和事实，不含任何结论
    result["facts"] = {
        "customer": order.customer,
        "inquiry_no": order.inquiry_no,
        "date": order.date,
        "urgent": bool(order.urgent),
        "item_count": result["item_count"],
        "total_quantity": total_quantity,
        "setup_fee": setup_fee,
        "expedite_multiplier": multiplier,
        "subtotal": subtotal,
        "total": total,
        "items": [
            {
                "part_name": row["part_name"],
                "material": row["material"],
                "quantity": row["quantity"],
                "unit": row["unit"],
                "weight_kg": row["weight_kg"],
                "material_price_per_kg": row["material_price_per_kg"],
                "processes": row["processes"],
                "unit_price": row["unit_price"],
                "line_total": row["line_total"],
                "previous_unit_price": (
                    row["previous"]["unit_price"] if row["previous"] else None
                ),
                "previous_date": row["previous"]["date"] if row["previous"] else None,
                "change_pct": row["change_pct"],
                "reference_p50": (
                    row["reference"]["p50"] if row["reference"]["available"] else None
                ),
                "reference_n": (
                    row["reference"]["n"] if row["reference"]["available"] else 0
                ),
                "deviation_pct": row["deviation_pct"],
            }
            for row in line_items
        ],
        "violations": violation_dicts,
    }

    if archive:
        archive_quote(
            {
                "id": result["quote_id"],
                "customer": order.customer,
                "inquiry_no": order.inquiry_no,
                "total": total,
                "items": [
                    {
                        "part_name": row["part_name"],
                        "material": row["material"],
                        "quantity": row["quantity"],
                        "unit_price": row["unit_price"],
                        "line_total": row["line_total"],
                    }
                    for row in line_items
                ],
            }
        )

    return result
