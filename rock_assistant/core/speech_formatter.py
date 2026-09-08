"""Converte respostas textuais em uma versão adequada para síntese de fala."""

import re
from typing import Any, Iterable


_LABELS = {
    "status": "Status",
    "target": "Destinatário",
    "text": "Mensagem",
    "query": "Busca",
    "when": "Quando",
    "command": "Comando",
    "title": "Título",
    "snippet": "Resumo",
    "error": "Erro",
}


def _format_mapping(value: dict[Any, Any]) -> str:
    parts = []
    for key, item in value.items():
        label = _LABELS.get(str(key).lower(), str(key))
        formatted = format_for_speech(item)
        if formatted:
            parts.append(f"{label}: {formatted}")
    return ". ".join(parts)


def _format_iterable(value: Iterable[Any]) -> str:
    items = [format_for_speech(item) for item in value]
    items = [item for item in items if item]
    return ". ".join(items)


def _replace_symbols(text: str) -> str:
    replacements = (
        (r"!==", " diferente de "),
        (r"===", " exatamente igual a "),
        (r"!=", " diferente de "),
        (r"==", " igual a "),
        (r">=", " maior ou igual a "),
        (r"<=", " menor ou igual a "),
        (r"=>", " então "),
        (r"\+=", " mais igual a "),
        (r"-=", " menos igual a "),
        (r"\*=", " vezes igual a "),
        (r"/=", " dividido igual a "),
        (r"(?<![=])=(?!=)", " igual "),
        (r"&&", " e "),
        (r"\|\|", " ou "),
        (r"\+", " mais "),
        (r"(?<!\w)/(?!\w)", " barra "),
        (r"\|", " ou "),
        (r"_", " "),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def _format_text(text: str, intent: str | None = None) -> str:
    text = re.sub(r"```(?:\w+)?", "", text)
    text = text.replace("```", "")
    text = re.sub(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)", r"\1", text)

    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or re.fullmatch(r"[-_=*#`\s]{3,}", line):
            continue
        if re.match(r"^(?:🔗\s*)?Link\s*:", line, re.IGNORECASE):
            continue
        line = re.sub(r"^\[\d+\]\s*", "", line)
        line = re.sub(r"^(?:🔍|📝|💡|⚠️|❌|✅|🎯)\s*", "", line)
        line = re.sub(r"https?://\S+|www\.\S+", "", line)
        lines.append(line)

    prepared = " ".join(lines)
    prepared = _replace_symbols(prepared)
    prepared = re.sub(r"[{}\[\]<>]", " ", prepared)
    prepared = re.sub(r"[`*_#~]", "", prepared)
    prepared = re.sub(r"\s+", " ", prepared).strip(" .,:;-|")
    return prepared


def format_for_speech(value: Any, intent: str | None = None) -> str:
    """Retorna uma representação natural e curta de um resultado para o TTS."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return _format_mapping(value)
    if isinstance(value, (list, tuple, set)):
        return _format_iterable(value)
    return _format_text(str(value), intent=intent)
