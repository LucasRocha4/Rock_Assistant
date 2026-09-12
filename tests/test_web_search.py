import sys
from pathlib import Path
from unittest.mock import patch


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from rock_assistant.core.intent_parser import IntentParser
from rock_assistant.tools import web_search


def test_explicit_search_modes_are_structured():
    parser = IntentParser()

    assert parser.parse("busca em massa: preços de notebooks") == {
        "intent": "search",
        "payload": {"query": "preços de notebooks", "mode": "bulk"},
    }
    assert parser.parse("busca alvo específico: Sotam") == {
        "intent": "search",
        "payload": {"query": "Sotam", "mode": "target"},
    }
    assert parser.parse("busca tutoriais de Python") == {
        "intent": "search",
        "payload": {"query": "tutoriais de Python"},
    }


def test_structured_search_uses_fast_ddgs_result():
    result_item = {"title": "Resultado", "url": "https://example.test", "snippet": "Resumo"}
    with patch.object(web_search, "_ddgs_search", return_value=[result_item]):
        result = web_search.search_web_structured("consulta")

    assert result["status"] == "success"
    assert result["workers"] == 1
    assert result["results"] == [result_item]


def test_structured_search_rejects_lexical_false_positive():
    irrelevant = {
        "title": "Quem - Últimas Notícias",
        "url": "https://example.test/quem",
        "snippet": "Famosos e celebridades do momento.",
    }
    relevant = {
        "title": "Quem foi o jogador com mais gols da história?",
        "url": "https://example.test/futebol",
        "snippet": "O jogador marcou mais gols na história do futebol.",
    }
    with patch.object(web_search, "_ddgs_search", side_effect=[[irrelevant], [relevant]]):
        result = web_search.search_web_structured("quem foi o jogador com mais gols da história")

    assert result["status"] == "success"
    assert result["results"] == [relevant]


def test_structured_search_falls_back_to_workers():
    result_item = {"title": "Encontrado", "url": "https://example.test/result", "snippet": "ok"}
    with patch.object(web_search, "_ddgs_search", side_effect=[[], [result_item]]), patch.object(
        web_search.config, "SEARCH_DEADLINE", 1.0
    ), patch.object(web_search.config, "SEARCH_SCALE_INTERVAL", 0.5):
        result = web_search.search_web_structured("consulta", mode="target")

    assert result["status"] == "success"
    assert result["results"] == [result_item]
    assert result["attempts"] >= 1


def test_structured_search_honors_worker_ceiling_on_timeout():
    with patch.object(web_search, "_ddgs_search", return_value=[]), patch.object(
        web_search.config, "SEARCH_INITIAL_TIMEOUT", 0.01
    ), patch.object(web_search.config, "SEARCH_DEADLINE", 0.08), patch.object(
        web_search.config, "SEARCH_SCALE_INTERVAL", 0.01
    ), patch.object(web_search.config, "SEARCH_TARGET_INITIAL_WORKERS", 5), patch.object(
        web_search.config, "SEARCH_MAX_WORKERS", 20
    ):
        result = web_search.search_web_structured("consulta", mode="target")

    assert result["status"] == "timeout"
    assert result["workers"] <= 20