"""Normalização determinística de lembretes antes da persistência."""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Optional


@dataclass
class ReminderDraft:
    """Representa um lembrete pronto para confirmação ou persistência."""

    raw_text: str
    short_text: str
    kind: str
    importance: str
    when: Optional[str]
    scheduled_at: Optional[str]
    timezone: Optional[str]
    all_day: bool
    needs_confirmation: bool
    confirmation_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ReminderInterpreter:
    """Converte o payload textual atual em um rascunho estruturado."""

    IMPORTANCE_PATTERNS = (
        ("urgent", re.compile(r"\b(urgente|urgência|emergência|imediatamente)\b", re.I)),
        ("high", re.compile(r"\b(importante|prioridade|não esquecer|nao esquecer)\b", re.I)),
        ("low", re.compile(r"\b(quando puder|sem pressa|baixa prioridade)\b", re.I)),
    )
    SELF_MESSAGE_PATTERN = re.compile(
        r"\b(me entregue|me entregar|me avise|me diga|me informe|me comunique|me passe|para mim)\b",
        re.I,
    )
    TIME_PATTERN = re.compile(
        r"(?:às|as|ás|para as|para às|at)?\s*(\d{1,2})(?:[:h](\d{2}))?\s*(am|pm)?",
        re.I,
    )
    DATE_PATTERN = re.compile(
        r"(?:no dia|dia|data)\s+(\d{1,2})(?:/(\d{1,2})(?:/(\d{2,4}))?)?",
        re.I,
    )

    def interpret(
        self,
        payload: Dict[str, Any],
        *,
        now: Optional[datetime] = None,
    ) -> ReminderDraft:
        raw_text = str(payload.get("raw_text") or payload.get("text") or "").strip()
        text = str(payload.get("text") or raw_text).strip()
        when = self._clean_when(payload.get("when"))
        kind = self._detect_kind(raw_text, payload)
        importance = self._detect_importance(raw_text, payload.get("importance"))
        short_text = self._shorten(text)
        scheduled_at, all_day, temporal_reason = self._resolve_when(when, now=now)
        reference = now or datetime.now().astimezone()

        confirmation_reason = temporal_reason
        if not short_text:
            confirmation_reason = confirmation_reason or "a descrição do lembrete está vazia"
        if kind == "calendar_event" and not when:
            confirmation_reason = confirmation_reason or "o evento não possui data ou horário"

        return ReminderDraft(
            raw_text=raw_text,
            short_text=short_text,
            kind=kind,
            importance=importance,
            when=when,
            scheduled_at=scheduled_at,
            timezone=reference.tzname(),
            all_day=all_day,
            needs_confirmation=bool(confirmation_reason),
            confirmation_reason=confirmation_reason,
        )

    @staticmethod
    def _clean_when(value: Any) -> Optional[str]:
        cleaned = str(value or "").strip()
        return cleaned or None

    def _detect_kind(self, raw_text: str, payload: Dict[str, Any]) -> str:
        explicit_kind = str(payload.get("kind") or "").strip().lower()
        if explicit_kind in {"calendar_event", "self_message"}:
            return explicit_kind
        if self.SELF_MESSAGE_PATTERN.search(raw_text):
            return "self_message"
        return "calendar_event"

    def _detect_importance(self, text: str, explicit: Any = None) -> str:
        if str(explicit or "").lower() in {"low", "normal", "high", "urgent"}:
            return str(explicit).lower()
        explicit = text.lower()
        for importance, pattern in self.IMPORTANCE_PATTERNS:
            if pattern.search(explicit):
                return importance
        return "normal"

    @staticmethod
    def _shorten(text: str, limit: int = 120) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip(" .,:;-\n\t")
        cleaned = re.sub(
            r"^(?:por favor|você pode|pode|quero que|não esqueça de|nao esqueça de)\s+",
            "",
            cleaned,
            flags=re.I,
        ).strip()
        if len(cleaned) <= limit:
            return cleaned
        shortened = cleaned[: limit - 3].rsplit(" ", 1)[0].rstrip(" ,;:-")
        return f"{shortened}..."

    def _resolve_when(
        self,
        when: Optional[str],
        *,
        now: Optional[datetime] = None,
    ) -> tuple[Optional[str], bool, Optional[str]]:
        if not when:
            return None, False, None

        reference = now or datetime.now().astimezone()
        value = when.lower().strip()
        event_date: Optional[date] = None
        if "depois de amanhã" in value or "depois de amanha" in value:
            event_date = reference.date() + timedelta(days=2)
        elif "amanhã" in value or "amanha" in value:
            event_date = reference.date() + timedelta(days=1)
        elif "hoje" in value:
            event_date = reference.date()
        else:
            date_match = self.DATE_PATTERN.search(value)
            if date_match:
                day = int(date_match.group(1))
                month = int(date_match.group(2) or reference.month)
                year = int(date_match.group(3) or reference.year)
                if year < 100:
                    year += 2000
                try:
                    event_date = date(year, month, day)
                except ValueError:
                    return None, False, "a data informada é inválida"

        if event_date is None:
            weekday_names = {
                "segunda": 0, "segunda-feira": 0, "terça": 1, "terça-feira": 1,
                "terca": 1, "terca-feira": 1, "quarta": 2, "quarta-feira": 2,
                "quinta": 3, "quinta-feira": 3, "sexta": 4, "sexta-feira": 4,
                "sábado": 5, "sábado-feira": 5, "sabado": 5, "domingo": 6,
            }
            weekday = next((number for name, number in weekday_names.items() if name in value), None)
            if weekday is not None:
                days_ahead = (weekday - reference.weekday()) % 7 or 7
                event_date = reference.date() + timedelta(days=days_ahead)

        time_match = self.TIME_PATTERN.search(value)
        period_match = re.search(r"(?:pela|de|à|a)\s+(manhã|manha|tarde|noite)", value)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            meridiem = (time_match.group(3) or "").lower()
            if meridiem == "pm" and hour < 12:
                hour += 12
            if meridiem == "am" and hour == 12:
                hour = 0
            if hour > 23 or minute > 59:
                return None, False, "o horário informado é inválido"
        elif "meio-dia" in value or "meio dia" in value:
            hour, minute = 12, 0
        elif "meia-noite" in value or "meia noite" in value:
            hour, minute = 0, 0
        elif period_match:
            hour = {"manhã": 9, "manha": 9, "tarde": 15, "noite": 20}[period_match.group(1).lower()]
            minute = 0
        else:
            hour = minute = None

        if event_date is None:
            return None, False, "não foi possível identificar a data"
        if hour is None:
            return datetime.combine(event_date, time.min, tzinfo=reference.tzinfo).isoformat(), True, None
        return datetime.combine(event_date, time(hour, minute), tzinfo=reference.tzinfo).isoformat(), False, None
