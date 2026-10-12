"""Конфигурация из переменных окружения / .env (без внешних зависимостей)."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Минимальный загрузчик .env: KEY=VALUE, без перезаписи уже заданных vars."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(PROJECT_ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


class Settings:
    """Все настройки приложения. Ключи читаются из окружения или .env."""

    def __init__(self) -> None:
        # LLM: основной провайдер OpenRouter (бесплатная модель) + резерв GLM
        self.openrouter_api_key = _env("OPENROUTER_API_KEY")
        self.openrouter_base_url = _env(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/")
        self.llm_model = _env("LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")

        self.glm_api_key = _env("GLM_API_KEY")
        self.glm_base_url = _env("GLM_BASE_URL").rstrip("/")
        self.glm_model = _env("GLM_MODEL", "glm-4.5-flash")

        # эмбеддинги
        self.embed_model = _env("EMBED_MODEL", "openai/text-embedding-3-small")

        # хранилище
        self.db_path = Path(_env("DB_PATH", str(PROJECT_ROOT / "data" / "vetclinic.db")))
        self.services_path = Path(
            _env("SERVICES_PATH", str(PROJECT_ROOT / "data" / "services.json"))
        )

        # CORS для встраивания виджета в сайт
        self.allowed_origins = [
            o for o in _env("ALLOWED_ORIGINS", "*").split(",") if o
        ]

        self.request_timeout = float(_env("REQUEST_TIMEOUT", "60"))


settings = Settings()
