"""Юнит-тесты: парсинг JSON от LLM и логика извлечения полей заявки."""

import pytest

from app import store
from app.assistant import REQUIRED_BOOKING_FIELDS, FIELD_QUESTIONS
from app.llm import parse_json


class TestParseJson:
    def test_plain(self):
        assert parse_json('{"intent": "price"}') == {"intent": "price"}

    def test_code_fence(self):
        raw = '```json\n{"reply": "3000 руб."}\n```'
        assert parse_json(raw) == {"reply": "3000 руб."}

    def test_text_around(self):
        raw = 'Вот ответ: {"reply": "ок"} — если что, звоните'
        assert parse_json(raw) == {"reply": "ок"}

    def test_nested(self):
        raw = '{"booking": {"fields": {"phone": "+7 999"}}}'
        assert parse_json(raw)["booking"]["fields"]["phone"] == "+7 999"

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_json("никакого json здесь нет")


class TestBookingLogic:
    def test_required_fields_covered_by_questions(self):
        """На каждое обязательное поле есть уточняющий вопрос."""
        for f in REQUIRED_BOOKING_FIELDS:
            assert f in FIELD_QUESTIONS

    def test_appointment_created_with_all_fields(self, tmp_path):
        conn = store.connect(tmp_path / "t.db")
        appt_id = store.create_appointment(
            conn,
            {
                "session_id": "s1",
                "pet_name": "Мурка",
                "pet_type": "кошка",
                "service": "Первичный приём",
                "preferred_time": "завтра в 11",
                "phone": "+7 999 123-45-67",
            },
        )
        items = store.list_appointments(conn)
        assert len(items) == 1
        assert items[0]["id"] == appt_id
        assert items[0]["status"] == "new"
        assert items[0]["pet_name"] == "Мурка"

    def test_status_transitions(self, tmp_path):
        conn = store.connect(tmp_path / "t.db")
        appt_id = store.create_appointment(
            conn,
            {"session_id": "s", "pet_type": "пёс", "phone": "+79990000000"},
        )
        assert store.update_appointment_status(conn, appt_id, "confirmed")
        assert store.list_appointments(conn)[0]["status"] == "confirmed"
        assert not store.update_appointment_status(conn, appt_id, "nonsense")
        assert not store.update_appointment_status(conn, 999, "done")


class TestClean:
    def test_clean_values(self):
        from app.assistant import Assistant

        assert Assistant._clean(None) is None
        assert Assistant._clean("  Мурка  ") == "Мурка"
        assert Assistant._clean("null") is None
        assert Assistant._clean("нет") is None
        assert Assistant._clean("кошка\nвторой\nстрокой") == "кошка второй строкой"
