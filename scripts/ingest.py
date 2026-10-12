"""Ингест: data/services.json -> SQLite с эмбеддингами.

Эмбеддинги кэшируются в таблице embedding_cache, поэтому повторный запуск
не тратит токены: меняются только записи с новым текстом.

Запуск:
    python scripts/ingest.py            # data/services.json -> data/vetclinic.db
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import embeddings, store  # noqa: E402
from app.config import settings  # noqa: E402


def ingest(services_path=None, db_path=None) -> int:
    services_path = Path(services_path or settings.services_path)
    db_path = Path(db_path or settings.db_path)

    records = json.loads(services_path.read_text(encoding="utf-8"))
    conn = store.connect(db_path)

    # эмбеддинг каждой услуги: «категория + название» — так запросы вида
    # «сколько стоит операция» лучше попадают в хирургию
    texts = [f"{r['category']}. {r['name']}" for r in records]
    vectors = embeddings.embed(texts, conn)

    rows = []
    for r, v in zip(records, vectors):
        rows.append({**r, "embedding": json.dumps(v)})
    store.replace_services(conn, rows)
    count = len(rows)
    conn.close()
    return count


if __name__ == "__main__":
    n = ingest()
    print(f"OK: {n} услуг с эмбеддингами -> {settings.db_path}")
