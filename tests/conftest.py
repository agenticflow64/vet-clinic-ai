"""Общие фикстуры тестов.

Все тесты офлайн:
- эмбеддинги подменяются детерминированным хеш-векторизатором
  (char-3-граммы -> 256-мерный вектор): для русских фраз вида
  «кастрация кота» против «Кастрация кота» близость высокая;
- LLM подменяется ScriptedLLM с заготовленными ответами по режимам.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import embeddings as embeddings_mod  # noqa: E402
from app import llm as llm_mod  # noqa: E402
from app import store  # noqa: E402
from app.assistant import Assistant  # noqa: E402
from app.search import PriceSearch  # noqa: E402


# --- детерминированный «эмбеддинг» без сети ---------------------------------


def hash_embed(text: str) -> list[float]:
    """Char-3-граммы с хешированием в 256-мерный вектор, l2-нормировка."""
    dim = 256
    v = [0.0] * dim
    t = text.lower()
    for i in range(len(t) - 2):
        gram = t[i : i + 3]
        h = hash(gram) % dim
        sign = 1.0 if (hash(gram + "#") & 1) else -1.0
        v[h] += sign
    import math

    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class HashEmbedder:
    def __call__(self, texts, conn):
        return [hash_embed(t) for t in texts]


# --- скриптованный LLM --------------------------------------------------------


class ScriptedLLM:
    """Отвечает по заготовкам: ищет в промпте маркер режима и возвращает JSON."""

    def __init__(self):
        self.classify_intent = "price"
        self.triage = {
            "urgency": "soon",
            "reply": "Опишите состояние подробнее.",
        }
        self.price_reply = None  # если None — возвращаем контекст прайса как reply
        self.extraction = {}
        self.calls = []

    def __call__(self, messages, **kwargs):
        prompt = messages[-1]["content"]
        self.calls.append(prompt)
        if "Определи намерение" in prompt:
            return json.dumps({"intent": self.classify_intent}, ensure_ascii=False)
        if "urgency" in prompt and "surgery_now" in prompt:
            return json.dumps(self.triage, ensure_ascii=False)
        if "pet_name" in prompt and "preferred_time" in prompt:
            return json.dumps(self.extraction, ensure_ascii=False)
        if "Прайс (фрагмент" in prompt:
            if self.price_reply:
                return json.dumps({"reply": self.price_reply}, ensure_ascii=False)
            # вырезаем контекст и возвращаем его — так тест видит, что нашёл поиск
            ctx = prompt.split("Прайс (фрагмент, найденный поиском):\n")[1].split("\n\nВопрос")[0]
            return json.dumps({"reply": ctx}, ensure_ascii=False)
        return json.dumps({"reply": "Чем могу помочь?"}, ensure_ascii=False)


@pytest.fixture()
def offline_env(monkeypatch, tmp_path):
    """Подменяет embed и chat, создаёт чистую базу с мини-корпусом."""
    monkeypatch.setattr(embeddings_mod, "embed", HashEmbedder())
    scripted = ScriptedLLM()
    monkeypatch.setattr(llm_mod, "chat", scripted)
    monkeypatch.setattr("app.assistant.llm.chat", scripted)

    db = tmp_path / "test.db"
    conn = store.connect(db)

    corpus = [
        {"id": 1, "category": "Хирургия", "name": "Кастрация кота", "price": 3000, "source": "full"},
        {"id": 2, "category": "Хирургия", "name": "Стерилизация кошки", "price": 5000, "source": "curated"},
        {"id": 3, "category": "УЗИ диагностика", "name": "УЗИ брюшной полости комплексное", "price": 2500, "source": "curated"},
        {"id": 4, "category": "Приём и консультация", "name": "Первичный приём", "price": 1200, "source": "full"},
        {"id": 5, "category": "Вакцинация и профилактика", "name": "Вакцинация от бешенства", "price": 700, "source": "curated"},
        {"id": 6, "category": "Лаборатория и диагностика", "name": "Клинический анализ крови", "price": 900, "source": "full"},
    ]
    rows = [{**r, "embedding": json.dumps(hash_embed(f"{r['category']}. {r['name']}"))} for r in corpus]
    store.replace_services(conn, rows)

    search = PriceSearch(store.get_services(conn), conn)
    assistant = Assistant(conn, search)

    # интеграционные тесты через TestClient работают на этой же офлайн-базе
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "assistant", assistant)
    monkeypatch.setattr(main_mod, "_conn", conn)

    return {"conn": conn, "assistant": assistant, "llm": scripted, "search": search, "corpus": corpus}
