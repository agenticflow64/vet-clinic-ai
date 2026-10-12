"""Поиск по прайсу: косинусная близость в чистом Python.

Корпус — ~350 векторов по 1536 измерений; полный перебор занимает
единицы миллисекунд, поэтому векторная БД (pgvector и т.п.) не нужна.
Если корпус вырастет до десятков тысяч записей — переезд на pgvector
не меняет интерфейс search().
"""

import json

from . import embeddings


class PriceSearch:
    def __init__(self, services: list[dict], conn):
        self.conn = conn
        self._items: list[dict] = []
        for s in services:
            if not s.get("embedding"):
                continue
            vec = json.loads(s["embedding"]) if isinstance(s["embedding"], str) else s["embedding"]
            self._items.append(
                {
                    "id": s["id"],
                    "category": s["category"],
                    "name": s["name"],
                    "price": s["price"],
                    "source": s.get("source", "full"),
                    "vector": embeddings.normalize(vec),
                }
            )

    def __len__(self) -> int:
        return len(self._items)

    def search(self, query: str, k: int = 6) -> list[dict]:
        """Top-k услуг по косинусной близости (векторы нормированы)."""
        query_vec = embeddings.embed([query], self.conn)[0]
        qv = embeddings.normalize(query_vec)
        scored = []
        for item in self._items:
            score = sum(a * b for a, b in zip(qv, item["vector"]))
            scored.append((score, item))
        scored.sort(key=lambda pair: -pair[0])
        results = []
        for score, item in scored[:k]:
            r = {key: item[key] for key in ("id", "category", "name", "price", "source")}
            r["score"] = round(score, 4)
            results.append(r)
        return results
