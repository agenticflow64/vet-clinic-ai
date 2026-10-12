"""LLM-клиент с цепочкой fallback: OpenRouter (бесплатная модель) -> GLM.

Оба провайдера говорят на OpenAI-совместимом протоколе /chat/completions,
поэтому один и тот же код работает с обоими.
"""

import json
import logging
import re

import httpx

from .config import settings

log = logging.getLogger(__name__)


class LLMError(Exception):
    """Все провайдеры недоступны."""


def _providers() -> list[dict]:
    ps = []
    if settings.openrouter_api_key:
        ps.append(
            {
                "name": "openrouter",
                "base_url": settings.openrouter_base_url,
                "api_key": settings.openrouter_api_key,
                "model": settings.llm_model,
            }
        )
    if settings.glm_api_key and settings.glm_base_url:
        ps.append(
            {
                "name": "glm",
                "base_url": settings.glm_base_url,
                "api_key": settings.glm_api_key,
                "model": settings.glm_model,
            }
        )
    return ps


def chat(
    messages: list[dict],
    *,
    temperature: float = 0.3,
    max_tokens: int = 800,
) -> str:
    """Один запрос к LLM с перебором провайдеров. Возвращает текст ответа."""
    last_err: Exception | None = None
    for p in _providers():
        for attempt in (1, 2):  # по одной повторной попытке на провайдера
            try:
                r = httpx.post(
                    f"{p['base_url']}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {p['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": p["model"],
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
                raise ValueError(f"пустой ответ от {p['name']}")
            except Exception as e:  # noqa: BLE001 — переключаемся на следующий
                last_err = e
                log.warning("llm %s попытка %d не удалась: %s", p["name"], attempt, e)
    raise LLMError(f"ни один провайдер не ответил: {last_err}")


def parse_json(text: str) -> dict:
    """Достаёт JSON-объект из ответа LLM.

    Бесплатные модели любят оборачивать JSON в ```json ...``` или добавлять
    текст до/после — ищем первую {...} сбалансированную последовательность.
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
