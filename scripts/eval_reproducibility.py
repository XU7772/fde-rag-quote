# -*- coding: utf-8 -*-
"""
可复现性检查。

这是整个项目最重要的一条不变量：
    同样的输入，在**不同的进程**里跑，必须得到逐字节相同的结果。

为什么强调不同进程：
  在同一个进程里连跑三次是弱的 —— 模块级缓存、随机种子状态、字典顺序
  都会被复用，掩盖掉真正的不确定性。这里每次都用子进程重新 import。

默认用法：
    python scripts/eval_reproducibility.py
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"


def _fingerprint() -> str:
    sys.path.insert(0, str(BACKEND))
    from types import SimpleNamespace

    from pricing import calculate_quote

    def item(p, m, proc, w, q, d=7):
        return SimpleNamespace(
            part_name=p, material=m, process=proc,
            weight_kg=w, quantity=q, unit="件", delivery_days=d,
        )

    order = SimpleNamespace(
        customer="宏达精密机械有限公司",
        inquiry_no="INQ-2026-1031",
        date="2026-10-31",
        urgent=True,
    )
    items = [
        item("不锈钢法兰盘", "304不锈钢", "CNC车削、去毛刺", 0.85, 120),
        item("铝制散热片", "6061铝", "CNC铣削、去毛刺、阳极氧化", 0.28, 400),
        item("黄铜接头", "H62", "CNC车削", 0.18, 50),
    ]

    result = calculate_quote(order, items, archive=False)

    # quote_id 是 Q-20261031-153012 这种带秒级时间戳的单号，
    # 它本来就该随调用时间变化，不属于「计算结果」。
    # 如果把它算进指纹，测到的就是时钟而不是计价逻辑。
    result.pop("quote_id", None)

    blob = json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def main() -> None:
    runs = 3
    prints = []

    for i in range(runs):
        proc = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).resolve()), "--emit"],
            capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode != 0:
            print(f"第 {i + 1} 次运行失败：\n{proc.stderr}")
            raise SystemExit(1)
        prints.append(proc.stdout.strip())
        print(f"  第 {i + 1} 次  sha256 = {prints[-1]}")

    ok = len(set(prints)) == 1
    print()
    print(f"跨进程一致：{'是' if ok else '否'}")
    if not ok:
        print("  同一个输入得到了不同结果 —— 报价不可复现，这是 blocker。")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    if "--emit" in sys.argv:
        print(_fingerprint())
    else:
        main()
