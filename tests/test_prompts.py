"""Юнит-тесты промптов: ключевые требования режимов закреплены в текстах."""

from app import prompts


def test_triage_prompt_has_disclaimer_terms():
    p = prompts.TRIAGE_PROMPT.format(system="S", message="кот не ест")
    # промпт запрещает диагнозы и требует осторожности
    assert "никогда не ставь диагноз" in p
    assert "surgery_now" in p and "routine" in p


def test_disclaimer_text_is_ready_for_user():
    assert "не заменяет консультацию ветеринарного врача" in prompts.DISCLAIMER
    assert "25-83-19" in prompts.DISCLAIMER  # телефон клиники для экстренного случая


def test_price_prompt_forbids_invention():
    p = prompts.PRICE_PROMPT.format(system="S", context="ctx", message="m")
    assert "не выдумывай" in p
    assert "уточняется у администратора" in p


def test_price_prompt_demands_exact_prices():
    items = [
        {"category": "Хирургия", "name": "Кастрация кота", "price": 3000},
        {"category": "УЗИ", "name": "Ветлаб", "price": None},
    ]
    ctx = prompts.format_price_context(items)
    assert "Кастрация кота — 3000 руб." in ctx
    assert "уточняется" in ctx  # price None/0 -> «уточняется»


def test_booking_prompt_fields():
    p = prompts.BOOKING_PROMPT.format(system="S", history="h", message="m")
    for field in ("pet_name", "pet_type", "service", "preferred_time", "phone"):
        assert field in p
    assert "null" in p  # отсутствующие поля — null, не выдумывать


def test_classify_prompt_intents():
    p = prompts.CLASSIFY_PROMPT.format(system="S", history="", message="m")
    for intent in ("price", "triage", "booking", "smalltalk"):
        assert intent in p


def test_history_formatting():
    history = [
        {"role": "user", "content": "привет"},
        {"role": "assistant", "content": "здравствуйте"},
        {"role": "system", "content": "скрытое"},  # должно быть отфильтровано выше
    ]
    text = prompts.format_history(history[:2])
    assert "Пользователь: привет" in text
    assert "Ассистент: здравствуйте" in text


def test_system_persona_has_clinic_contacts():
    assert "Каштанка" in prompts.SYSTEM_PERSONA
    assert "10:00" in prompts.SYSTEM_PERSONA
