"""GPU-сервис эмбеддингов: отдельный процесс на хосте (вне docker/k8s).

Основное приложение (FastAPI, py3.14) не тянет torch: оно ходит сюда по HTTP
на localhost:8111. Так GPU-зависимости живут отдельным окружением
embeddings_service/.venv (py3.12), и в прод-окружении сервис стартует
на GPU-хосте без проброса GPU в контейнеры приложения.

Модель: BAAI/bge-m3 (мультиязычная, отличная для русского).
Fallback-цепочка при недоступности HF-хаба:
    intfloat/multilingual-e5-large
    sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

Запуск:
    embeddings_service/.venv/bin/python embeddings_service/server.py [порт]
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8111

MODEL_CANDIDATES = [
    "BAAI/bge-m3",
    "intfloat/multilingual-e5-large",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
]

# e5-модели требуют префиксы query:/passage:; bge-m3 — нет
PREFIX_MODELS = {"intfloat/multilingual-e5-large"}

_model = None
_model_name = None


def load_model():
    global _model, _model_name
    from sentence_transformers import SentenceTransformer

    errors = []
    for name in MODEL_CANDIDATES:
        try:
            device = "cuda"  # GPU на хосте; при недоступности упадёт — так и задумано
            model = SentenceTransformer(name, device=device)
            # прогрев
            model.encode(["прогрев"], normalize_embeddings=True)
            _model, _model_name = model, name
            print(f"[embeddings] модель {name} на {device}", flush=True)
            return
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    raise RuntimeError("ни одна модель не загрузилась: " + "; ".join(errors))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = json.dumps(
                {"status": "ok", "model": _model_name, "dim": _model.get_sentence_embedding_dimension()}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/embed":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        texts = payload.get("texts", [])
        prefix = payload.get("prefix", "passage")
        if _model_name in PREFIX_MODELS:
            texts = [f"{prefix}: {t}" for t in texts]
        vectors = _model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        body = json.dumps({"model": _model_name, "vectors": vectors.tolist()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # меньше шума в логах
        pass


if __name__ == "__main__":
    load_model()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[embeddings] слушаю 127.0.0.1:{PORT}", flush=True)
    server.serve_forever()
