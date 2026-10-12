"""Интеграционные тесты: подъём сервиса, RAG по прайсу, диалог -> заявка.

Полностью офлайн: эмбеддинги и LLM подменены (см. conftest.py).
"""

from fastapi.testclient import TestClient

from app import store
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_static_pages():
    for path in ("/demo", "/widget", "/admin", "/embed.js"):
        r = client.get(path)
        assert r.status_code == 200, path


class TestPriceMode:
    def test_price_question_finds_right_service(self, offline_env):
        """Вопрос по прайсу -> правильная услуга в top-1, цена названа."""
        offline_env["llm"].classify_intent = "price"
        r = client.post(
            "/api/chat", json={"message": "Сколько стоит кастрация кота?"}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["intent"] == "price"
        matched = data["matched"]
        assert matched, "должен вернуть найденные услуги"
        assert matched[0]["name"] == "Кастрация кота"
        assert matched[0]["price"] == 3000
        # ScriptedLLM возвращает контекст прайса как reply — цена должна быть в нём
        assert "3000" in data["reply"]

    def test_search_ranks_relevant_first(self, offline_env):
        s = offline_env["search"]
        for query, expected in [
            ("стерилизация кошки сколько стоит", "Стерилизация кошки"),
            ("узи брюшной полости цена", "УЗИ брюшной полости комплексное"),
            ("прививка от бешенства", "Вакцинация от бешенства"),
        ]:
            top = s.search(query, k=3)[0]
            assert top["name"] == expected, f"{query!r}: {top['name']!r}"


class TestTriageMode:
    def test_triage_urgency_and_disclaimer(self, offline_env):
        offline_env["llm"].classify_intent = "triage"
        offline_env["llm"].triage = {
            "urgency": "surgery_now",
            "reply": "Немедленно везите в клинику.",
        }
        r = client.post("/api/chat", json={"message": "Кот сутки не может пописать"})
        data = r.json()
        assert data["intent"] == "triage"
        assert data["urgency"] == "surgery_now"
        assert data["urgency_label"] == "срочно к врачу"
        # дисклеймер крепится всегда
        assert "не заменяет консультацию ветеринарного врача" in data["reply"]

    def test_invalid_urgency_falls_back_to_cautious(self, offline_env):
        offline_env["llm"].classify_intent = "triage"
        offline_env["llm"].triage = {"urgency": "что-то странное", "reply": "Ответ"}
        r = client.post("/api/chat", json={"message": "собака хромает"})
        assert r.json()["urgency"] == "soon"  # осторожный вариант по умолчанию


class TestBookingFlow:
    def test_dialog_creates_appointment(self, offline_env):
        """Многоходовой диалог -> структурированная заявка в SQLite."""
        llm = offline_env["llm"]
        llm.classify_intent = "booking"

        # шаг 1: пользователь хочет записаться, полей ещё нет
        llm.extraction = {"pet_name": None, "pet_type": None, "service": None,
                          "preferred_time": None, "phone": None}
        r1 = client.post("/api/chat", json={"message": "Хочу записаться на приём"})
        d1 = r1.json()
        assert "appointment_id" not in d1
        assert d1["booking"]["missing"] == ["pet_type", "preferred_time", "phone"]

        session_id = d1["session_id"]

        # шаг 2: вид животного и кличка
        llm.extraction = {"pet_name": "Мурка", "pet_type": "кошка", "service": None,
                          "preferred_time": None, "phone": None}
        r2 = client.post("/api/chat", json={"session_id": session_id, "message": "Кошка, кличка Мурка"})
        assert "appointment_id" not in r2.json()
        assert r2.json()["booking"]["missing"] == ["preferred_time", "phone"]

        # шаг 3: время и телефон -> заявка создаётся
        llm.extraction = {"pet_name": "Мурка", "pet_type": "кошка", "service": "Первичный приём",
                          "preferred_time": "завтра в 11:00", "phone": "+7 999 123-45-67"}
        r3 = client.post(
            "/api/chat",
            json={"session_id": session_id, "message": "Завтра в 11 утра, телефон +7 999 123-45-67"},
        )
        d3 = r3.json()
        assert d3.get("appointment_id"), d3
        assert d3["booking"]["missing"] == []
        assert "+7 999 123-45-67" in d3["reply"]

        # заявка в базе
        appts = client.get("/api/appointments").json()
        mine = [a for a in appts if a["session_id"] == session_id]
        assert len(mine) == 1
        a = mine[0]
        assert a["pet_name"] == "Мурка"
        assert a["pet_type"] == "кошка"
        assert a["service"] == "Первичный приём"
        assert a["preferred_time"] == "завтра в 11:00"
        assert a["phone"] == "+7 999 123-45-67"
        assert a["status"] == "new"

    def test_booking_continues_after_smalltalk_answer(self, offline_env):
        """Отвечает телефоном без слова «записаться» — сессия продолжает запись."""
        llm = offline_env["llm"]
        llm.classify_intent = "booking"
        llm.extraction = {"pet_name": None, "pet_type": "собака", "service": None,
                          "preferred_time": "в субботу", "phone": None}
        r1 = client.post("/api/chat", json={"message": "Запишите собаку на субботу"})
        sid = r1.json()["session_id"]

        # пользователь просто называет телефон; классификатор сказал smalltalk
        llm.classify_intent = "smalltalk"
        llm.extraction = {"pet_name": None, "pet_type": "собака", "service": None,
                          "preferred_time": "в субботу", "phone": "+7 900 000-00-00"}
        r2 = client.post("/api/chat", json={"session_id": sid, "message": "+7 900 000-00-00"})
        assert r2.json().get("appointment_id"), "заявка должна создаться"

    def test_admin_updates_status(self, offline_env):
        llm = offline_env["llm"]
        llm.classify_intent = "booking"
        llm.extraction = {"pet_name": "Барсик", "pet_type": "кот",
                          "service": None, "preferred_time": "сегодня вечером",
                          "phone": "+7 911 111-11-11"}
        r = client.post("/api/chat", json={"message": "Запишите кота на сегодня вечером, +7 911 111-11-11"})
        appt_id = r.json()["appointment_id"]

        r = client.patch(f"/api/appointments/{appt_id}", json={"status": "confirmed"})
        assert r.status_code == 200
        appts = client.get("/api/appointments").json()
        assert next(a for a in appts if a["id"] == appt_id)["status"] == "confirmed"

        r = client.patch(f"/api/appointments/{appt_id}", json={"status": "nope"})
        assert r.status_code == 400
