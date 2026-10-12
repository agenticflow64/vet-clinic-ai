"""Оркестратор ассистента: классификация -> один из трёх режимов.

Поток обработки сообщения:
  1. LLM классифицирует намерение (price / triage / booking / smalltalk);
  2. price  -> поиск по прайсу (косинус) -> ответ LLM с точными ценами;
  3. triage -> LLM оценивает срочность, к ответу всегда крепится дисклеймер;
  4. booking -> LLM извлекает поля заявки из диалога; когда обязательные поля
     собраны — заявка создаётся в SQLite и пользователь получает подтверждение.

Если сессия уже в режиме записи (был intent=booking, заявка не создана),
любое сообщение продолжает запись — иначе телефон/время ушли бы в smalltalk.
"""

import logging
import re

from . import llm, prompts, store

log = logging.getLogger(__name__)

INTENTS = ("price", "triage", "booking", "smalltalk")
URGENCY_LABELS = {
    "surgery_now": "срочно к врачу",
    "soon": "приём в ближайшие дни",
    "routine": "планово",
}

# обязательные поля заявки: без них заявка не создаётся
REQUIRED_BOOKING_FIELDS = ("pet_type", "preferred_time", "phone")

FIELD_QUESTIONS = {
    "pet_type": "Какое животное ведёте: кот, собака, кто-то ещё?",
    "preferred_time": "Когда вам удобно прийти? День и примерное время.",
    "phone": "Оставьте телефон, перезвоним и подтвердим запись.",
}


class Assistant:
    def __init__(self, conn, search):
        self.conn = conn
        self.search = search

    # --- публичная точка входа ---------------------------------------------

    def handle_message(self, session_id: str, message: str) -> dict:
        message = message.strip()
        if not message:
            return {"reply": "Напишите ваш вопрос.", "intent": "smalltalk"}

        history = store.get_history(self.conn, session_id)
        history = [m for m in history if m["role"] in ("user", "assistant")]

        intent = self._classify(message, history)
        if intent == "smalltalk" and store.has_pending_booking(self.conn, session_id):
            intent = "booking"

        store.add_message(self.conn, session_id, "user", message, intent=intent)

        handlers = {
            "price": self._handle_price,
            "triage": self._handle_triage,
            "booking": self._handle_booking,
            "smalltalk": self._handle_smalltalk,
        }
        result = handlers[intent](session_id, message, history)
        result["intent"] = intent

        store.add_message(
            self.conn, session_id, "assistant", result["reply"], intent=intent
        )
        return result

    # --- режимы -------------------------------------------------------------

    def _handle_price(self, session_id: str, message: str, history: list[dict]) -> dict:
        found = self.search.search(message, k=6)
        context = prompts.format_price_context(found)
        prompt = prompts.PRICE_PROMPT.format(
            system=prompts.SYSTEM_PERSONA, context=context, message=message
        )
        reply = self._ask_json(prompt, fallback="Не нашёл ответ в прайсе.")
        return {"reply": reply, "matched": found}

    def _handle_triage(self, session_id: str, message: str, history: list[dict]) -> dict:
        prompt = prompts.TRIAGE_PROMPT.format(
            system=prompts.SYSTEM_PERSONA, message=message
        )
        data = self._ask_json_raw(prompt)
        urgency = (data.get("urgency") or "").strip()
        if urgency not in URGENCY_LABELS:
            urgency = "soon"  # при сомнении — осторожный вариант
        reply = (data.get("reply") or "").strip() or "Опишите состояние питомца подробнее."
        if prompts.DISCLAIMER.split(".")[0] not in reply:
            reply = f"{reply}\n\n{prompts.DISCLAIMER}"
        return {
            "reply": reply,
            "urgency": urgency,
            "urgency_label": URGENCY_LABELS[urgency],
        }

    def _handle_booking(self, session_id: str, message: str, history: list[dict]) -> dict:
        dialog = prompts.format_history(history) + f"\nПользователь: {message}"
        prompt = prompts.BOOKING_PROMPT.format(
            system=prompts.SYSTEM_PERSONA, history=dialog, message=message
        )
        data = self._ask_json_raw(prompt)

        fields = {
            key: self._clean(data.get(key))
            for key in ("pet_name", "pet_type", "service", "preferred_time", "phone")
        }

        missing = [f for f in REQUIRED_BOOKING_FIELDS if not fields.get(f)]
        if missing:
            question = " ".join(FIELD_QUESTIONS[f] for f in missing)
            return {"reply": question, "booking": {"fields": fields, "missing": missing}}

        appointment_id = store.create_appointment(
            self.conn, {"session_id": session_id, **fields}
        )
        pet_name_part = f" по кличке {fields['pet_name']}" if fields.get("pet_name") else ""
        service_part = f"Услуга: {fields['service']}. " if fields.get("service") else ""
        reply = prompts.BOOKING_CONFIRM.format(
            phone=fields["phone"],
            pet_type=fields["pet_type"],
            pet_name_part=pet_name_part,
            service_part=service_part,
            time=fields["preferred_time"],
        )
        return {
            "reply": reply,
            "appointment_id": appointment_id,
            "booking": {"fields": fields, "missing": []},
        }

    def _handle_smalltalk(self, session_id: str, message: str, history: list[dict]) -> dict:
        prompt = (
            f"{prompts.SYSTEM_PERSONA}\n\n"
            "Ответь на сообщение пользователя в 1-2 предложения. Если вопрос "
            "не о клинике — мягко верни разговор к теме: услуги, цены, запись "
            "на приём, состояние питомца.\n\n"
            f"История:\n{prompts.format_history(history)}\n\n"
            f"Сообщение: «{message}»\n\n"
            'Ответь строго JSON: {"reply": "текст"}'
        )
        reply = self._ask_json(prompt, fallback="Чем могу помочь?")
        return {"reply": reply}

    # --- внутреннее -----------------------------------------------------------

    def _classify(self, message: str, history: list[dict]) -> str:
        prompt = prompts.CLASSIFY_PROMPT.format(
            system=prompts.SYSTEM_PERSONA,
            history=prompts.format_history(history[-6:]),
            message=message,
        )
        try:
            data = llm.parse_json(llm.chat([{"role": "user", "content": prompt}]))
            intent = data.get("intent", "").strip()
            return intent if intent in INTENTS else "price"
        except Exception:  # noqa: BLE001
            return "price"

    def _ask_json_raw(self, prompt: str) -> dict:
        answer = llm.chat([{"role": "user", "content": prompt}])
        try:
            return llm.parse_json(answer)
        except ValueError:
            return {}

    def _ask_json(self, prompt: str, fallback: str) -> str:
        data = self._ask_json_raw(prompt)
        reply = (data.get("reply") or "").strip()
        return reply or fallback

    @staticmethod
    def _clean(value) -> str | None:
        if value is None:
            return None
        s = re.sub(r"\s+", " ", str(value)).strip()
        if not s or s.lower() in ("null", "none", "нет", "-"):
            return None
        return s
