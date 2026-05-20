"""D3-4: Embedding provider wrapper.

封装 OpenAI text-embedding-3-small（1536 维，与 ``memories.embedding`` 对齐）。

为什么直连 OpenAI 而不复用 OpenRouter？
- OpenRouter 当前对 ``/embeddings`` 路由的兼容性不稳定（404 / 模型未列入路由）。
- D2 系列已经在用 OpenRouter chat，新加一个 OpenAI key 不增加架构复杂度，
  调用面也小（仅 D3-4 + D4-1 retrieve 阶段会用到）。

接口
====
``async embed(texts: list[str], trace_id: str) -> EmbedResult``
- 单次最多 N 条（OpenAI 限 8191 token / 输入，本模块默认 batch=64）
- 超时 / 5xx → 一次重试，仍失败 → ``EmbedResult.error`` 非空
- 返回向量与输入同序，长度严格 == len(texts)

绝不抛异常：错误以 ``EmbedResult.error`` 返回，调用方根据是否为空决定后续行为。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
from loguru import logger

from core.config import settings


OPENAI_BASE = "https://api.openai.com/v1"
TIMEOUT_S = 20.0
RETRY_COUNT = 1  # 失败后再试 1 次


@dataclass
class EmbedResult:
    """单次 embed 调用的结果。

    - ``vectors`` 与输入文本同序、同长度（当 ``error`` 为空时）。
    - ``error`` 非空时 ``vectors`` 为空列表。
    """

    vectors: list[list[float]] = field(default_factory=list)
    model_used: str = ""
    usage: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    error: Optional[str] = None


async def embed(texts: list[str], trace_id: str) -> EmbedResult:
    """对一批文本求 embedding。

    Args:
        texts: 非空字符串列表。空字符串会被替换成空格（OpenAI 拒绝空输入）。
        trace_id: 全链路 trace。

    Returns:
        EmbedResult；失败时 ``error`` 非空、``vectors`` 为空。
    """
    if not texts:
        return EmbedResult()

    if not settings.OPENAI_API_KEY:
        return EmbedResult(error="OPENAI_API_KEY_MISSING")

    model = settings.EMBEDDING_MODEL or "text-embedding-3-small"
    cleaned = [(t if t and t.strip() else " ") for t in texts]

    body = {"model": model, "input": cleaned}
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{OPENAI_BASE}/embeddings"

    log = logger.bind(
        trace_id=trace_id,
        component="embedder",
        model=model,
        batch_size=len(cleaned),
    )

    last_error: Optional[str] = None
    started = time.time()

    for attempt in range(RETRY_COUNT + 1):
        log.bind(attempt=attempt).info("embedder.call.start")
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            last_error = f"timeout:{exc}"
            log.bind(attempt=attempt).warning("embedder.call.timeout")
            continue
        except Exception as exc:
            last_error = f"network:{type(exc).__name__}:{exc}"
            log.bind(attempt=attempt, error_type=type(exc).__name__).warning("embedder.call.network_error")
            continue

        if resp.status_code >= 500:
            last_error = f"5xx:{resp.status_code}:{resp.text[:200]}"
            log.bind(attempt=attempt, status=resp.status_code).warning("embedder.call.5xx")
            continue
        if resp.status_code >= 400:
            # 4xx 不重试（多半是 key 错 / 余额不足 / 模型不存在）
            last_error = f"4xx:{resp.status_code}:{resp.text[:200]}"
            log.bind(status=resp.status_code).error("embedder.call.4xx")
            return EmbedResult(
                model_used=model,
                latency_ms=(time.time() - started) * 1000,
                error=last_error,
            )

        try:
            data = resp.json()
        except ValueError as exc:
            last_error = f"json_decode:{exc}"
            log.warning("embedder.call.bad_json")
            continue

        vectors = _extract_vectors(data, expected_len=len(cleaned))
        if vectors is None:
            last_error = "vector_count_mismatch"
            log.warning("embedder.call.vector_count_mismatch")
            continue

        latency = (time.time() - started) * 1000
        usage = data.get("usage", {}) or {}
        log.bind(
            duration_ms=round(latency, 1),
            tokens=usage.get("total_tokens"),
        ).info("embedder.call.ok")

        return EmbedResult(
            vectors=vectors,
            model_used=model,
            usage=usage,
            latency_ms=latency,
        )

    log.bind(error=last_error).error("embedder.call.failed_after_retries")
    return EmbedResult(
        model_used=model,
        latency_ms=(time.time() - started) * 1000,
        error=last_error or "unknown",
    )


def _extract_vectors(data: dict, expected_len: int) -> Optional[list[list[float]]]:
    """从 OpenAI 风格响应中提取 ``data[*].embedding``，按 ``index`` 排序。"""
    if not isinstance(data, dict):
        return None
    items = data.get("data")
    if not isinstance(items, list) or len(items) != expected_len:
        return None

    indexed: list[tuple[int, list[float]]] = []
    for item in items:
        if not isinstance(item, dict):
            return None
        emb = item.get("embedding")
        idx = item.get("index", len(indexed))
        if not isinstance(emb, list) or not emb:
            return None
        try:
            idx_int = int(idx)
        except (TypeError, ValueError):
            idx_int = len(indexed)
        indexed.append((idx_int, [float(x) for x in emb]))

    indexed.sort(key=lambda p: p[0])
    return [v for _, v in indexed]
