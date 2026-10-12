"""Эмбеддинги: клиент локального GPU-сервиса (embeddings_service/server.py).

Архитектура: torch и модель живут отдельным процессом на GPU-хосте
(RTX 5060 Ti, BAAI/bge-m3), приложение обращается к нему по HTTP на
127.0.0.1:8111 — так GPU-зависимости не попадают в окружение сервиса,
а в docker/k8s не нужен GPU-passthrough в контейнер приложения.

Если сервис не поднят, клиент стартует его сам (один раз, фоновым
процессом) и ждёт готовности. Результаты кэшируются в SQLite по хешу
текста + имени модели, поэтому повторный ингест бесплатен.
"""

import hashlib
import logging
import os
import subprocess
import time
from pathlib import Path

import httpx

from .config import settings
from . import store

log = logging.getLogger(__name__)

EMBED_SERVER_URL = os.environ.get("EMBED_SERVER_URL", "http://127.0.0.1:8111")
EMBED_SERVER_STARTUP_TIMEOUT = float(os.environ.get("EMBED_SERVER_STARTUP_TIMEOUT", "180"))
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def embed(texts: list[str], conn) -> list[list[float]]:
    """Эмбеддинги для списка текстов: кэш -> локальный GPU-сервис."""
    result: list[list[float] | None] = [None] * len(texts)
    todo: list[int] = []
    for i, t in enumerate(texts):
        cached = store.cache_get(conn, text_hash(t), settings.embed_model)
        if cached is not None:
            result[i] = cached
        else:
            todo.append(i)

    if todo:
        _ensure_server()
        vectors, model = _embed_http([texts[i] for i in todo], prefix="passage")
        if model and model != settings.embed_model:
            log.info("модель эмбеддингов: %s (в конфиге был %s)", model, settings.embed_model)
            settings.embed_model = model
        for i, v in zip(todo, vectors):
            result[i] = v
            store.cache_put(conn, text_hash(texts[i]), settings.embed_model, v)
    return result  # type: ignore[return-value]


def embed_query(text: str, conn) -> list[float]:
    """Эмбеддинг поискового запроса (для e5-моделей — префикс query:)."""
    cached = store.cache_get(conn, text_hash("q:" + text), settings.embed_model)
    if cached is not None:
        return cached
    _ensure_server()
    vectors, model = _embed_http([text], prefix="query")
    if model and model != settings.embed_model:
        settings.embed_model = model
    store.cache_put(conn, text_hash("q:" + text), settings.embed_model, vectors[0])
    return vectors[0]


# --- HTTP-клиент и автозапуск сервиса -----------------------------------------


def _server_ready(timeout: float = 1.0) -> bool:
    try:
        r = httpx.get(f"{EMBED_SERVER_URL}/health", timeout=timeout)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


_started = False


def _ensure_server() -> None:
    global _started
    if _started or _server_ready():
        _started = True
        return
    log.info("GPU-сервис эмбеддингов не отвечает, запускаю: %s", EMBED_SERVER_URL)
    venv_python = _PROJECT_ROOT / "embeddings_service" / ".venv" / "bin" / "python"
    if not venv_python.exists():
        raise RuntimeError(
            f"нет {venv_python} — создайте окружение: "
            "uv venv embeddings_service/.venv --python 3.12 && "
            "uv pip install --python embeddings_service/.venv/bin/python sentence-transformers"
        )
    subprocess.Popen(
        [str(venv_python), str(_PROJECT_ROOT / "embeddings_service" / "server.py")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + EMBED_SERVER_STARTUP_TIMEOUT
    while time.time() < deadline:
        if _server_ready():
            _started = True
            return
        time.sleep(1.0)
    raise RuntimeError("GPU-сервис эмбеддингов не поднялся за отведённое время")


def _embed_http(texts: list[str], prefix: str = "passage") -> tuple[list[list[float]], str]:
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            r = httpx.post(
                f"{EMBED_SERVER_URL}/embed",
                json={"texts": texts, "prefix": prefix},
                timeout=settings.request_timeout,
            )
            r.raise_for_status()
            data = r.json()
            return data["vectors"], data.get("model", "")
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("embeddings попытка %d не удалась: %s", attempt + 1, e)
            time.sleep(1 + attempt)
    raise RuntimeError(f"GPU-сервис эмбеддингов недоступен: {last_err}")


def normalize(v: list[float]) -> list[float]:
    """L2-нормировка (bge-m3 уже нормирует, здесь — защита от других моделей)."""
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]
