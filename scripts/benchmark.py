"""Живые замеры качества ассистента (требует ключи в .env).

Что меряет:
  1. Точность поиска по прайсу: 12 вопросов, проверяем, что ожидаемая услуга
     в top-1 / top-3 выдачи и что LLM назвал правильную цену.
  2. Триаж: 3 сценария, совпадение уровня срочности с ожидаемым.
  3. Диалог -> заявка end-to-end: время полного многоходового диалога.

Результат печатается таблицей и сохраняется в docs/benchmark.md.

Запуск:
    set -a; source .env; set +a
    python scripts/benchmark.py
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store  # noqa: E402
from app.assistant import Assistant  # noqa: E402
from app.config import settings  # noqa: E402
from app.search import PriceSearch  # noqa: E402

# --- 1. вопросы по прайсу: (вопрос, ожидаемая услуга, ожидаемая цена) --------

PRICE_QUESTIONS = [
    ("Сколько стоит стерилизация кошки?", "Стерилизация кошки", 5000),
    ("Во сколько обойдётся кастрация кота?", "Кастрация кота", 3000),
    ("Какая цена на УЗИ брюшной полости?", "УЗИ брюшной полости комплексное", 2500),
    ("Сколько стоит УЗИ сердца собаке?", "УЗИ сердца ЭхоКГ", 3000),
    ("Сколько стоит первичный приём?", "Первичный приём", 1200),
    ("Сколько стоит прививка от бешенства?", "Вакцинация от бешенства", 700),
    ("Сколько стоит чипирование животного?", "Чипирование", 800),
    ("Сколько стоит клинический анализ крови?", "Клинический анализ крови", 900),
    ("Цена на стрижку когтей?", "Стрижка когтей", 500),
    ("Сколько стоит сутки в стационаре?", "Сутки в стационаре", 900),
    ("Сколько стоит осмотр дерматолога?", "Осмотр дерматолога", 1500),
    ("Сколько стоит обработка от блох и клещей?", "Обработка от блох и клещей", 500),
]

# --- 2. сценарии триажа: (описание, ожидаемая срочность) ----------------------

TRIAGE_SCENARIOS = [
    (
        "Кот уже больше суток не может пописать, мечется в лотке и кричит",
        "surgery_now",
    ),
    ("Собака хромает на переднюю лапу уже третий день, но ест и гуляет", "soon"),
    ("Хочу записать котёнка на плановую вакцинацию на следующей неделе", "routine"),
]

# --- 3. диалог для end-to-end заявки -------------------------------------------

BOOKING_DIALOG = [
    "Привет, хочу записать собаку к врачу",
    "Лабрадор, кличка Барон",
    "На субботу примерно к 12 дня",
    "+7 927 100-20-30",
]


def run_price_benchmark(search) -> tuple[int, int, int, list[str]]:
    top1 = top3 = price_ok = 0
    details = []
    for question, expected_name, expected_price in PRICE_QUESTIONS:
        found = search.search(question, k=6)
        names = [f["name"] for f in found]
        hit1 = expected_name in names[:1]
        hit3 = expected_name in names[:3]
        top1 += hit1
        top3 += hit3
        details.append(
            f"| {question} | {expected_name} | "
            f"{'top-1' if hit1 else ('top-3' if hit3 else 'мимо')} |"
        )
    return top1, top3, len(PRICE_QUESTIONS), details


def run_price_llm_check(assistant) -> int:
    """LLM должен назвать точную цену ожидаемой услуги."""
    ok = 0
    for question, expected_name, expected_price in PRICE_QUESTIONS:
        try:
            r = assistant.handle_message(store.new_session_id(), question)
            if str(expected_price) in r["reply"]:
                ok += 1
        except Exception:  # noqa: BLE001
            pass
    return ok


def run_triage_benchmark(assistant) -> tuple[int, list[str]]:
    ok = 0
    details = []
    for description, expected in TRIAGE_SCENARIOS:
        r = assistant.handle_message(store.new_session_id(), description)
        hit = r.get("urgency") == expected
        ok += hit
        details.append(f"| {description[:50]}… | {expected} | {r.get('urgency')} |")
    return ok, details


def run_booking_e2e(assistant) -> tuple[float, int]:
    t0 = time.time()
    sid = store.new_session_id()
    for msg in BOOKING_DIALOG:
        r = assistant.handle_message(sid, msg)
    dt = time.time() - t0
    appts = store.list_appointments(_conn)
    created = [a for a in appts if a["session_id"] == sid]
    return dt, (created[0]["id"] if created else 0)


def main() -> None:
    global _conn
    _conn = store.connect(settings.db_path)
    search = PriceSearch(store.get_services(_conn), _conn)
    assistant = Assistant(_conn, search)

    print("== 1. Поиск по прайсу (эмбеддинги, без LLM) ==")
    top1, top3, total, price_details = run_price_benchmark(search)
    print(f"top-1: {top1}/{total}, top-3: {top3}/{total}")

    print("== 1b. Ответ LLM называет точную цену ==")
    price_ok = run_price_llm_check(assistant)
    print(f"цена названа: {price_ok}/{total}")

    print("== 2. Триаж ==")
    triage_ok, triage_details = run_triage_benchmark(assistant)
    print(f"срочность верна: {triage_ok}/{len(TRIAGE_SCENARIOS)}")

    print("== 3. Диалог -> заявка (end-to-end) ==")
    dt, appt_id = run_booking_e2e(assistant)
    print(f"время: {dt:.1f} с, заявка id={appt_id or 'НЕ СОЗДАНА'}")

    report = build_report(
        top1, top3, total, price_ok, price_details,
        triage_ok, triage_details, dt, appt_id,
    )
    out = Path(__file__).parent.parent / "docs" / "benchmark.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"отчёт: {out}")


def build_report(top1, top3, total, price_ok, price_details, triage_ok, triage_details, dt, appt_id):
    now = time.strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Замеры качества (демо)",
        "",
        f"_Локальные замеры на демо-стенде, дата: {now}. ",
        "Модель: nemotron-3-super (OpenRouter, free), эмбеддинги: text-embedding-3-small._",
        "",
        "## 1. Вопросы по прайсу",
        "",
        f"- топ-1 поиск: **{top1}/{total}**",
        f"- топ-3 поиск: **{top3}/{total}**",
        f"- LLM назвал точную цену: **{price_ok}/{total}**",
        "",
        "| Вопрос | Ожидаемая услуга | Поиск |",
        "|---|---|---|",
        *price_details,
        "",
        "## 2. Триаж",
        "",
        f"- срочность определена верно: **{triage_ok}/{len(triage_details)}**",
        "",
        "| Сценарий | Ожидание | Факт |",
        "|---|---|---|",
        *triage_details,
        "",
        "## 3. Диалог → заявка (end-to-end)",
        "",
        f"- 4 реплики диалога, заявка id={appt_id}: **{dt:.1f} с**",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
