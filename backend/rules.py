# -*- coding: utf-8 -*-
"""
工艺规则：从自然语言到确定性判断。

这个模块里 **没有任何 LLM 调用**。
rules.md 是人写的自然语言，但它的结构是固定的，所以能被解析成条件对象；
解析之后就是普通的 Python 比较，同样的输入永远得到同样的输出。

RAG 在这里只有一个降级用途：
  规则多到几百条时，先用向量把「可能相关的规则」筛出来，再逐条判断。
  规则少的时候直接全量跑 —— 两种模式的结果必须一致，由 eval_rules.py 保证。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from rag.embed import cosine, get_embedder
from storage import resolve_material

RULES_PATH = Path(__file__).resolve().parent / "data" / "rules.md"

_FIELD_ALIASES = {
    "weight": "weight_kg",
    "weight_kg": "weight_kg",
    "material": "material",
    "process": "process",
    "part_name": "part_name",
    "quantity": "quantity",
    "delivery_days": "delivery_days",
    "urgent": "urgent",
    "unit_price": "unit_price",
}

_COND_RE = re.compile(
    r"^(?P<field>[a-zA-Z_]+)\s*(?P<op>=|!=|>=|<=|>|<|contains|lacks|in)\s*(?P<value>.+)$"
)

TEXT_FIELDS = {"material", "process", "part_name"}
NUMERIC_OPS = {">", "<", ">=", "<="}


@dataclass(frozen=True)
class Condition:
    field: str
    op: str
    value: str

    def describe(self) -> str:
        return f"{self.field} {self.op} {self.value}"


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    level: str
    message: str
    conditions: tuple[Condition, ...]
    raw: str = field(default="", compare=False)

    def text(self) -> str:
        """给检索用的可读文本。"""
        return f"{self.title} {self.message} " + " ".join(
            c.describe() for c in self.conditions
        )


@dataclass(frozen=True)
class Violation:
    rule_id: str
    title: str
    level: str
    message: str
    part_name: str
    item_index: int

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "level": self.level,
            "message": self.message,
            "part_name": self.part_name,
            "item_index": self.item_index,
        }


# ---------------------------------------------------------------- 解析


def parse_rules(path: Path | None = None) -> list[Rule]:
    text = (path or RULES_PATH).read_text(encoding="utf-8")
    rules: list[Rule] = []
    current: dict | None = None
    conditions: list[Condition] = []

    def flush() -> None:
        if not current:
            return
        if not conditions:
            raise ValueError(f"规则 {current['id']} 没有任何条件")
        rules.append(
            Rule(
                id=current["id"],
                title=current["title"],
                level=current["level"],
                message=current["message"],
                conditions=tuple(conditions),
                raw=current["raw"],
            )
        )

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("## "):
            flush()
            head = stripped[3:].strip()
            rule_id, _, title = head.partition(" ")
            current = {
                "id": rule_id,
                "title": title.strip() or rule_id,
                "level": "warn",
                "message": "",
                "raw": head,
            }
            conditions = []
            continue

        if current is None or not stripped.startswith("- "):
            continue

        key, _, value = stripped[2:].partition(":")
        key, value = key.strip().lower(), value.strip()

        if key in ("when", "and"):
            m = _COND_RE.match(value)
            if not m:
                raise ValueError(f"规则 {current['id']} 的条件写法无法解析：{value}")
            fld = _FIELD_ALIASES.get(m.group("field"))
            if not fld:
                raise ValueError(f"规则 {current['id']} 使用了未知字段：{m.group('field')}")
            conditions.append(Condition(fld, m.group("op"), m.group("value")))
        elif key == "level":
            if value not in ("error", "warn", "info"):
                raise ValueError(f"规则 {current['id']} 的 level 非法：{value}")
            current["level"] = value
        elif key == "message":
            current["message"] = value

    flush()
    return rules


# ---------------------------------------------------------------- 判断


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _eval_condition(cond: Condition, ctx: dict) -> bool:
    actual = ctx.get(cond.field)

    if cond.field in ("material",):
        got = resolve_material(str(actual or ""))
        want = resolve_material(cond.value)
        if cond.op == "=":
            return got is not None and got == want
        if cond.op == "!=":
            return got != want
        if cond.op == "in":
            wanted = {resolve_material(v.strip()) for v in cond.value.split(",")}
            return got in wanted
        return False

    if cond.field in ("process", "part_name"):
        text = str(actual or "")
        if cond.op == "contains":
            return cond.value in text
        if cond.op == "lacks":
            return cond.value not in text
        if cond.op == "=":
            return text.strip() == cond.value.strip()
        if cond.op == "!=":
            return text.strip() != cond.value.strip()
        return False

    if cond.field == "urgent":
        want = cond.value.strip().lower() in ("true", "1", "yes")
        return bool(actual) == want if cond.op == "=" else bool(actual) != want

    # 数值类
    got_num = _as_float(actual)
    want_num = _as_float(cond.value)
    if got_num is None or want_num is None:
        return False
    if cond.op in NUMERIC_OPS:
        return {
            ">": got_num > want_num,
            "<": got_num < want_num,
            ">=": got_num >= want_num,
            "<=": got_num <= want_num,
        }[cond.op]
    if cond.op == "=":
        return got_num == want_num
    if cond.op == "!=":
        return got_num != want_num
    return False


def _build_context(item, order, unit_price: float | None) -> dict:
    """item / order 既可能是 Pydantic 模型，也可能是 dict。"""
    def get(obj, name, default=None):
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    return {
        "material": get(item, "material", ""),
        "process": get(item, "process", ""),
        "part_name": get(item, "part_name", ""),
        "weight_kg": get(item, "weight_kg"),
        "quantity": get(item, "quantity"),
        "delivery_days": get(item, "delivery_days"),
        "urgent": get(order, "urgent", False),
        "unit_price": unit_price,
    }


def check(
    items: list,
    order,
    unit_prices: list[float | None] | None = None,
    rules: list[Rule] | None = None,
) -> list[Violation]:
    """全量校验：每条规则 × 每个零件。"""
    rules = rules if rules is not None else parse_rules()
    unit_prices = unit_prices or [None] * len(items)

    violations: list[Violation] = []
    for idx, item in enumerate(items):
        ctx = _build_context(item, order, unit_prices[idx] if idx < len(unit_prices) else None)
        for rule in rules:
            if all(_eval_condition(c, ctx) for c in rule.conditions):
                violations.append(
                    Violation(
                        rule_id=rule.id,
                        title=rule.title,
                        level=rule.level,
                        message=rule.message,
                        part_name=str(ctx["part_name"]),
                        item_index=idx,
                    )
                )
    return violations


# ---------------------------------------------------------------- 检索预筛


def select_rules(
    items: list,
    order,
    rules: list[Rule] | None = None,
    top_k: int = 4,
) -> list[Rule]:
    """规则量大时先用向量粗筛。

    数值型规则（重量/数量/交期/急单/单价）永远保留 —— 它们和文本无关，
    靠语义相似度去筛只会漏。文本型规则才做相似度竞争。
    """
    rules = rules if rules is not None else parse_rules()
    always = [r for r in rules if all(c.field not in TEXT_FIELDS for c in r.conditions)]
    text_rules = [r for r in rules if any(c.field in TEXT_FIELDS for c in r.conditions)]

    embedder = get_embedder()
    rule_vecs = {r.id: embedder.encode(r.text()) for r in text_rules}

    picked: dict[str, Rule] = {r.id: r for r in always}
    for item in items:
        ctx = _build_context(item, order, None)
        q = embedder.encode(
            f"{ctx['part_name']} {ctx['material']} {ctx['process']}"
        )
        scored = sorted(
            ((cosine(q, rule_vecs[r.id]), r) for r in text_rules),
            key=lambda x: -x[0],
        )
        for _, rule in scored[:top_k]:
            picked[rule.id] = rule

    return [r for r in rules if r.id in picked]


def has_blocking(violations: list[Violation]) -> bool:
    return any(v.level == "error" for v in violations)
