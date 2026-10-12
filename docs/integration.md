# Встраивание в Astro-сайт kashtanka64.ru

Ассистент — отдельный сервис: сайт не меняет свой стек и не получает
Python-зависимостей. Оба способа ниже не требуют сборочных шагов на стороне
Astro — только разметка.

## Способ 1: скрипт-загрузчик (плавающая кнопка)

В базовый layout Astro (например, `src/layouts/BaseLayout.astro`), перед
закрывающим `</body>`:

```astro
<script
  is:inline
  src="https://assistant.kashtanka64.ru/embed.js"
  data-theme="light"
  data-accent="c2563a"
  defer
></script>
```

Скрипт создаёт плавающую кнопку 🐾 и панель чата (iframe `/widget`).
Параметры:

| data-атрибут | Значение | По умолчанию |
|---|---|---|
| `data-theme` | `light` \| `dark` | `light` |
| `data-accent` | акцентный цвет (hex без `#`) | `c2563a` |
| `data-origin` | базовый URL сервиса | тот же origin, где лежит embed.js |

Тему можно синхронизировать с переключателем сайта (у kashtanka64.ru уже
есть dark/light): при переключении перезаписать `<script>` атрибут и
переинициализировать, либо просто задать тему через localStorage до загрузки.

## Способ 2: встроенная секция (iframe в страницу)

Компонент `src/components/AiAssistant.astro`:

```astro
---
const title = Astro.props.title ?? "Онлайн-ассистент";
---

<section class="ai-assistant">
  <h2>{title}</h2>
  <iframe
    src="https://assistant.kashtanka64.ru/widget?theme=light&accent=c2563a"
    title="AI-ассистент клиники"
    style="width:100%;max-width:420px;height:620px;border:1px solid #e8e1d9;border-radius:16px"
    loading="lazy"
  ></iframe>
  <p class="ai-assistant__note">
    Ассистент не заменяет консультацию ветеринарного врача.
  </p>
</section>
```

Дробим на страницу «Вопросы» или в блок контактов.

## CORS

API уже отвечает `Access-Control-Allow-Origin` из переменной `ALLOWED_ORIGINS`.
Для продакшена в `.env` сервиса ассистента:

```
ALLOWED_ORIGINS=https://kashtanka64.ru
```

Для локальной разработки Astro (по умолчанию :4321):

```
ALLOWED_ORIGINS=http://localhost:4321,https://kashtanka64.ru
```

Звёздочка `*` (по умолчанию в демо) на проде не нужна: эндпоинты только
`POST /api/chat`, `GET/PATCH /api/appointments` — но лучше явно.

## API (кратко)

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/chat` | `{session_id?, message}` → `{reply, intent, matched?, urgency?, appointment_id?, session_id}` |
| GET | `/api/appointments` | список заявок |
| PATCH | `/api/appointments/{id}` | `{status: new|confirmed|done|cancelled}` |
| GET | `/api/health` | живость + число услуг |

`session_id` генерируется сервером при первом сообщении, виджет хранит его
в localStorage. Полная схема — `/api/docs` (OpenAPI).

## Размещение

Стенд рассчитан на отдельный deployment (текущее демо — голый хост с GPU для
эмбеддингов):

- сервис FastAPI — контейнер без GPU (эмбеддинги по HTTP к GPU-хосту);
- `embeddings_service` — процесс на GPU-хосте (torch + bge-m3), в k8s это
  nodeSelector на GPU-ноду или отдельный сервис вне кластера;
- SQLite → заменить на Postgres при росте (интерфейс `store.py` это позволяет);

## Админка

`/admin` — страница заявок. В реальном встраивании закрыть basic-auth на
ingress или подключить авторизацию существующей админки сайта.
