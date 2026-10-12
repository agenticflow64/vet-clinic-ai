"""LLM-клиент: только бесплатные модели OpenRouter, цепочка fallback.

Цепочка задаётся переменной LLM_MODELS (через запятую). Порядок по умолчанию
выбран по замерам стабильности JSON-вывода, русскому языку и скорости
(см. docs/benchmark.md, раздел «Выбор модели»):

    nvidia/nemotron-3.5-lightning:free     — основная: 6/6 валидного JSON,
                                             русский отличный; reasoning-модель,
                                             поэтому max_tokens держим большими
    nvidia/nemotron-3-ultra-550b-a55b:free — резерв 1: 5/6 JSON, ~4-6 с
    google/gemma-4-31b-it:free             — резерв 2: стабильна, но у апстрима
                                             бывают перманентные 429

poolside/laguna-s-2.1:free из списка владельца отбракована: 2/6 валидного JSON
и постоянные 429. GLM из цепочки убран решением владельца: генерация — только
OpenRouter free.
"""

import json
import logging
import re

import httpx

from .config import settings

log = logging.getLogger(__name__)

DEFAULT_MODEL_CHAIN = (
    "nvidia/nemotron-3.5-lightning:free,"
    "nvidia/nemotron-3-ultra-550b-a55b:free,"
    "google/gemma-4-31b-it:free"
)


class LLMError(Exception):
    """Все модели недоступны."""


def _models() -> list[str]:
    raw = settings.llm_models or DEFAULT_MODEL_CHAIN
    return [m.strip() for m in raw.split(",") if m.strip()]


def chat(
    messages: list[dict],
    *,
    temperature: float = 0.3,
    max_tokens: int = 2500,
) -> str:
    """Один запрос к LLM: перебор моделей цепочки, по 2 попытки на каждую."""
    if not settings.openrouter_api_key:
        raise LLMError("OPENROUTER_API_KEY не задан")
    last_err: Exception | None = None
    for model in _models():
        for attempt in (1, 2):
            try:
                r = httpx.post(
                    f"{settings.openrouter_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.openrouter_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=settings.request_timeout,
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                if content and content.strip():
                    return content
                raise ValueError(f"пустой ответ от {model}")
            except Exception as e:  # noqa: BLE001 — следующая модель цепочки
                last_err = e
                log.warning("llm %s попытка %d не удалась: %s", model, attempt, e)
    raise LLMError(f"ни одна модель цепочки не ответила: {last_err}")


def parse_json(text: str) -> dict:
    """Достаёт JSON-объект из ответа LLM.

    Бесплатные модели любят оборачивать JSON в ```json ...``` или добавлять
    текст до/после — ищем первую сбалансированную {...} последовательность.
    """
    text = text.strip()
    # вырезаем code fence, если есть
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    # ищем сбалансированный объект
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"в ответе LLM нет валидного JSON: {text[:200]!r}")
