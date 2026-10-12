"""Эмбеддинги через OpenRouter (openai/text-embedding-3-small) с кэшем в SQLite.

Корpus маленький (~350 записей), поэтому:
  - кэш полный: повторный ингест не тратит токены;
  - в тестах функцию embed подменяют детерминированным хеш-векторизатором.
"""

import hashlib
import logging
import math
import time

import httpx

from .config import settings
from . import store

log = logging.getLogger(__name__)


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def embed(texts: list[str], conn) -> list[list[float]]:
    """Эмбеддинги для списка текстов: сначала кэш, потом API, результат в кэш."""
    result: list[list[float] | None] = [None] * len(texts)
    todo: list[int] = []
    for i, t in enumerate(texts):
        cached = store.cache_get(conn, text_hash(t), settings.embed_model)
        if cached is not None:
            result[i] = cached
        else:
            todo.append(i)

    if todo:
        CHUNK = 64  # API ограничивает размер пачки
        for start in range(0, len(todo), CHUNK):
            idxs = todo[start : start + CHUNK]
            vectors = _embed_api([texts[i] for i in idxs])
            for i, v in zip(idxs, vectors):
                result[i] = v
                store.cache_put(conn, text_hash(texts[i]), settings.embed_model, v)
    return result  # type: ignore[return-value]


def _embed_api(texts: list[str]) -> list[list[float]]:
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            r = httpx.post(
                f"{settings.openrouter_base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": settings.embed_model, "input": texts},
                timeout=settings.request_timeout,
            )
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            return [d["embedding"] for d in data]
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("embeddings попытка %d не удалась: %s", attempt + 1, e)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"эмбеддинги недоступны: {last_err}")


def normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]
