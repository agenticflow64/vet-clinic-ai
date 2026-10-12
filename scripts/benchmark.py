"""Живые замеры качества ассистента (требует ключи в .env и GPU-сервис эмбеддингов).

Что меряет:
  1. Точность поиска по прайсу: 12 вопросов, ожидаемая услуга в top-1 / top-3.
  2. Точность ответа LLM: названа верная цена ожидаемой услуги.
  3. Триаж: 3 сценария, совпадение срочности с ожидаемой.
  4. Диалог -> заявка end-to-end: время полного многоходового диалога.

Результат печатается в консоль и сохраняется в docs/benchmark.md.

Запуск:
    set -a; source .env; set +a
    python scripts/benchmark.py
"""

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
    ("Сколько стоит чипирование животного?", "Чипирование", 1500),
    ("Сколько стоит клинический анализ крови?", "Клинический анализ крови", 600),
    ("Сколько стоит подстричь когти?", "Стрижка когтей 1 категория", 400),
    ("Сколько стоит осмотр дерматолога?", "Осмотр дерматолога", 1500),
    ("Сколько стоит обработать собаку от блох и клещей?", "Обработка от блох и клещей", 500),
    ("Сколько стоит чистка зубов ультразвуком (санация ротовой полости)?", "Санация ротовой полости ультразвуковым скайлером 1 категория", 1500),
]

# --- 2. сценарии триажа: (описание, ожидаемая срочность) ----------------------

TRIAGE_SCENARIOS = [
    (
        "Кот уже больше суток не может пописать, мечется в лотке и кричит",
        "surgery_now",
    ),
    ("Собака хромает на переднюю лапу уже третий день, но ест и гуляет", "soon"),
    ("Котёнку три месяца, надо начинать плановые прививки — подскажите, насколько это срочно", "routine"),
]

# --- 3. диалог для end-to-end заявки -------------------------------------------

BOOKING_DIALOG = [
    "Привет, хочу записать собаку к врачу",
    "Лабрадор, кличка Барон",
    "На субботу примерно к 12 дня",
    "+7 927 100-20-30",
]


def run_price_benchmark(search) -> tuple[int, int, list[str]]:
    top1 = top3 = 0
    details = []
    for question, expected_name, expected_price in PRICE_QUESTIONS:
        found = search.search(question, k=6)
        names = [f["name"] for f in found]
        hit1 = expected_name in names[:1]
        hit3 = expected_name in names[:3]
        top1 += hit1
        top3 += hit3
        rank = "top-1" if hit1 else ("top-3" if hit3 else "мимо")
        details.append(f"| {question} | {expected_name} | {rank} |")
    return top1, top3, details


def _digits_only(s: str) -> str:
    """«5 000 руб.» и «5000 руб.» должны сравниваться одинаково."""
    return "".join(ch for ch in s if ch.isdigit())


def run_price_llm_check(assistant) -> tuple[int, list[str]]:
    """LLM должен назвать точную цену ожидаемой услуги."""
    ok = 0
    details = []
    for question, expected_name, expected_price in PRICE_QUESTIONS:
        try:
            r = assistant.handle_message(store.new_session_id(), question)
            hit = str(expected_price) in _digits_only(r["reply"])
            ok += hit
            details.append(f"| {question} | {expected_price} руб. | {'да' if hit else 'НЕТ: ' + r['reply'][:60]} |")
        except Exception as e:  # noqa: BLE001
            details.append(f"| {question} | {expected_price} руб. | ошибка: {e} |")
    return ok, details


def run_triage_benchmark(assistant) -> tuple[int, list[str]]:
    ok = 0
    details = []
    for description, expected in TRIAGE_SCENARIOS:
        try:
            r = assistant.handle_message(store.new_session_id(), description)
            hit = r.get("urgency") == expected
            ok += hit
            details.append(f"| {description[:50]}… | {expected} | {r.get('urgency')} |")
        except Exception as e:  # noqa: BLE001
            details.append(f"| {description[:50]}… | {expected} | ошибка: {e} |")
    return ok, details


def run_booking_e2e(assistant, conn) -> tuple[float, int]:
    t0 = time.time()
    sid = store.new_session_id()
    for msg in BOOKING_DIALOG:
        assistant.handle_message(sid, msg)
    dt = time.time() - t0
    created = [a for a in store.list_appointments(conn) if a["session_id"] == sid]
    return dt, (created[0]["id"] if created else 0)


def main() -> None:
    conn = store.connect(settings.db_path)
    search = PriceSearch(store.get_services(conn), conn)
    assistant = Assistant(conn, search)

    print("== 1. Поиск по прайсу (bge-m3, без LLM) ==")
    top1, top3, price_details = run_price_benchmark(search)
    print(f"top-1: {top1}/{len(PRICE_QUESTIONS)}, top-3: {top3}/{len(PRICE_QUESTIONS)}")

    print("== 1b. Ответ LLM называет точную цену ==")
    price_ok, price_llm_details = run_price_llm_check(assistant)
    print(f"цена названа: {price_ok}/{len(PRICE_QUESTIONS)}")

    print("== 2. Триаж ==")
    triage_ok, triage_details = run_triage_benchmark(assistant)
    print(f"срочность верна: {triage_ok}/{len(TRIAGE_SCENARIOS)}")

    print("== 3. Диалог -> заявка (end-to-end) ==")
    dt, appt_id = run_booking_e2e(assistant, conn)
    print(f"время: {dt:.1f} с, заявка id={appt_id or 'НЕ СОЗДАНА'}")

    report = build_report(
        top1, top3, price_details, price_ok, price_llm_details,
        triage_ok, triage_details, dt, appt_id,
    )
    out = Path(__file__).parent.parent / "docs" / "benchmark.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"отчёт: {out}")


def build_report(top1, top3, price_details, price_ok, price_llm_details,
                 triage_ok, triage_details, dt, appt_id):
    now = time.strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Замеры качества (демо)",
        "",
        f"_Локальные замеры на демо-стенде, дата: {now}. ",
        "LLM: nvidia/nemotron-3.5-lightning (OpenRouter, free). "
        "Эмбеддинги: BAAI/bge-m3, локально на GPU (RTX 5060 Ti)._",
        "",
        "## 1. Вопросы по прайсу",
        "",
        f"- топ-1 поиск: **{top1}/{len(price_details)}**",
        f"- топ-3 поиск: **{top3}/{len(price_details)}**",
        f"- LLM назвал точную цену: **{price_ok}/{len(price_details)}**",
        "",
        "| Вопрос | Ожидаемая услуга | Поиск |",
        "|---|---|---|",
        *price_details,
        "",
        "| Вопрос | Ожидаемая цена | LLM назвал |",
        "|---|---|---|",
        *price_llm_details,
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
