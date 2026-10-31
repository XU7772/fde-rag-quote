# -*- coding: utf-8 -*-
"""
把一段中文文本变成向量。

为什么默认不用 sentence-transformers：
  1. 首次使用要下 ~100MB 权重，网络不好时整个项目跑不起来
  2. 这层是可插拔的接口，换模型不改调用方

所以默认用 HashEmbedder：字符 n-gram 哈希到固定维度。
它不是语义模型，但它对「法兰盘 / 法兰 / 法兰盘体」这类写法差异足够稳，
而且零依赖、零下载、结果完全确定 —— 这对评测很重要。

想换成真语义模型时，设置环境变量：
    RAG_EMBEDDER=st
需要先 pip install sentence-transformers。
"""

from __future__ import annotations

import math
import os
import re
import zlib
from typing import Protocol

DIM = 512


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _ngrams(text: str, ns: tuple[int, ...] = (1, 2, 3)) -> list[str]:
    """中文没有空格，按字符切 n-gram。"""
    s = _normalize(text)
    if not s:
        return []
    out: list[str] = []
    for n in ns:
        for i in range(len(s) - n + 1):
            out.append(s[i : i + n])
    return out


class Embedder(Protocol):
    name: str

    def encode(self, text: str) -> list[float]: ...


class HashEmbedder:
    """字符 n-gram -> 带符号哈希 -> 512 维，再做 L2 归一化。"""

    name = "hash-ngram"
    dim = DIM

    def encode(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for gram in _ngrams(text):
            h = zlib.crc32(gram.encode("utf-8"))
            idx = h % self.dim
            sign = 1.0 if (h >> 31) & 1 else -1.0
            vec[idx] += sign
        return _l2_normalize(vec)


class SentenceTransformerEmbedder:
    """可选的语义模型后端。没装依赖时会在 get_embedder 里被跳过。"""

    name = "sentence-transformers"

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5") -> None:
        from sentence_transformers import SentenceTransformer  # 延迟导入

        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    def encode(self, text: str) -> list[float]:
        return list(self._model.encode(text, normalize_embeddings=True))


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    """两边都已 L2 归一化时，点积就是余弦相似度。"""
    return sum(x * y for x, y in zip(a, b))


_EMBEDDER: Embedder | None = None


def get_embedder() -> Embedder:
    global _EMBEDDER
    if _EMBEDDER is not None:
        return _EMBEDDER

    choice = os.getenv("RAG_EMBEDDER", "hash").strip().lower()
    if choice == "st":
        try:
            _EMBEDDER = SentenceTransformerEmbedder()
            return _EMBEDDER
        except Exception as exc:  # 依赖没装或权重下载失败，静默降级
            print(f"[rag] sentence-transformers 不可用（{exc}），回退到 hash-ngram")

    _EMBEDDER = HashEmbedder()
    return _EMBEDDER
