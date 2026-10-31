# -*- coding: utf-8 -*-
"""
检索层对外只有一个入口：get_index()。

调用方（pricing.py）不应该关心是哈希向量还是 BGE 模型，
也不应该关心索引什么时候建好的。
"""

from __future__ import annotations

from rag.index import QuoteIndex
from storage import HISTORY

_INDEX: QuoteIndex | None = None


def get_index() -> QuoteIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = QuoteIndex(HISTORY)
    return _INDEX


def reset_index() -> None:
    """评测脚本换数据时用。"""
    global _INDEX
    _INDEX = None


__all__ = ["QuoteIndex", "get_index", "reset_index"]
