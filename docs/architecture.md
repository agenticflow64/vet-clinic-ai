# Архитектура

Демо-стенд AI-ассистента для сайта ветклиники kashtanka64.ru (сам сайт —
отдельный продовый проект на Kotlin/Quarkus + Astro + k8s, сюда не входит).

## Общая схема

```mermaid
flowchart LR
    subgraph client["Браузер посетителя"]
        site["Демо-страница / сайт клиники<br/>(Astro)"]
        widget["Чат-виджет<br/>iframe / embed.js"]
        admin["Админ-страница<br/>заявки"]
    end

    subgraph service["vet-clinic-ai (FastAPI, py3.14)"]
        api["API: POST /api/chat,<br/>GET/PATCH /api/appointments"]
        orchestrator["Ассистент-оркестратор<br/>классификатор намерения"]
        rag["RAG: косинусный поиск<br/>по прайсу"]
        booking["Извлечение полей заявки"]
        triage["Триаж<br/>+ дисклеймер"]
    end

    subgraph storage["SQLite (data/vetclinic.db)"]
        services[("Услуги + эмбеддинги<br/>347 записей")]
        appts[("Заявки на приём")]
        cache[("Кэш эмбеддингов")]
        msgs[("История диалогов")]
    end

    subgraph gpu["GPU-хост (отдельный процесс)"]
        embserver["embeddings_service<br/>sentence-transformers, bge-m3<br/>RTX 5060 Ti, :8111"]
    end

    llm["OpenRouter<br/>nemotron-3.5-lightning:free<br/>(fallback: ultra, gemma)"]
    pricelist["Прайс-листы .xlsx<br/>(репозиторий клиники, только чтение)"]

    widget -->|JSON| api
    admin -->|JSON| api
    api --> orchestrator
    orchestrator --> rag --> services
    orchestrator --> booking --> appts
    orchestrator --> triage
    orchestrator -->|LLM-вызовы| llm
    rag -->|HTTP /embed| embserver
    embserver --> cache
    orchestrator --> msgs
    pricelist -->|convert_pricelist.py| svcjson["data/services.json"]
    svcjson -->|ingest.py + bge-m3| services
```

## Поток обработки сообщения

```mermaid
sequenceDiagram
    participant U as Пользователь (виджет)
    participant A as Ассистент
    participant E as GPU-сервис (bge-m3)
    participant L as OpenRouter (free LLM)
    participant DB as SQLite

    U->>A: POST /api/chat {message}
    A->>L: классификация намерения (price/triage/booking/smalltalk)
    L-->>A: {"intent": "..."}

    alt price (вопрос о цене)
        A->>E: эмбеддинг запроса
        E-->>A: вектор
        A->>DB: косинусный поиск top-6
        A->>L: ответ по найденному фрагменту прайса
        L-->>A: {"reply": "Кастрация кота — 3000 руб."}
    else triage (состояние питомца)
        A->>L: оценка срочности по правилам промпта
        L-->>A: {"urgency": "...", "reply": "..."}
        A->>A: + дисклеймер «не заменяет консультацию врача»
    else booking (запись)
        A->>L: извлечение полей из диалога
        L-->>A: {pet_name, pet_type, service, preferred_time, phone}
        alt есть недостающие обязательные поля
            A-->>U: уточняющий вопрос
        else все поля собраны
            A->>DB: INSERT INTO appointments
            A-->>U: подтверждение заявки
        end
    end
```

## Ключевые решения

| Решение | Почему |
|---|---|
| SQLite + косинус в Python | 347 векторов × 1024 измерения: полный перебор — единицы мс; pgvector добавил бы инфраструктуру без выгоды. Интерфейс `search()` позволяет перейти позже без изменений вызывающего кода |
| Эмбеддинги отдельным GPU-процессом | bge-m3 на RTX 5060 Ti в собственном venv (py3.12 + torch), приложение (py3.14) ходит по HTTP. Нет GPU-passthrough в контейнеры, нет тяжёлых зависимостей в сервисе |
| Кэш эмбеддингов в SQLite | повторный ингест бесплатен; смена модели = новая запись по имени модели, старые кэши не мешают |
| LLM только OpenRouter free | без затрат на демо; цепочка fallback `LLM_MODELS`; GLM убран из цепочки, reasoning-модели требуют max_tokens ~2500 |
| Категории правилами, не LLM | детерминированность и покрытие тестами; данные для правил — категории с реального сайта |
| История диалога в SQLite | многходовая запись переживает перезапуск процесса; «незавершённая запись» определяется по intent=booking без созданной заявки |

## Ограничения демо

- Одно SQLite-соединение с lock — достаточно для демо, для продажи —
  пул/Postgres.
- Классификация намерения — отдельный LLM-вызов: +2–10 с на реплику на
  бесплатной reasoning-модели. В проде можно урезать до маленькой модели
  или локального классификатора.
- Админка без авторизации (закрывается на уровне ingress в реальном
  встраивании).
