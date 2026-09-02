"""Integração real de pesquisa na web utilizando DuckDuckGo Search (DDGS) e APIs complementares."""

import re
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Suprime avisos de depreciação/renomeação de pacote duckduckgo_search
warnings.filterwarnings("ignore", message=".*duckduckgo_search.*")
warnings.filterwarnings("ignore", message=".*renamed to.*")
warnings.filterwarnings("ignore", category=RuntimeWarning)

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from duckduckgo_search import DDGS
except ImportError:
    try:
        from ddgs import DDGS
    except ImportError:
        DDGS = None



def search_web_raw(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Executa a busca na web utilizando DuckDuckGo (DDGS) com estratégias resilientes de fallback.

    Retorna uma lista de dicionários contendo 'title', 'url' e 'snippet'.
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return []

    results: List[Dict[str, str]] = []

    # 1. Tentativa via DDGS text search
    if DDGS is not None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with DDGS() as ddgs:
                    raw_items = list(ddgs.text(cleaned_query, max_results=max_results))
                    if raw_items:
                        for item in raw_items:
                            results.append({
                                "title": item.get("title", "Sem título").strip(),
                                "url": item.get("href", item.get("url", "")).strip(),
                                "snippet": item.get("body", item.get("snippet", "")).strip(),
                            })
                        return results
        except Exception:
            pass

    # 2. Refinamento de termos para queries descritivas
    simplified = re.sub(
        r"\b(?:e|\d+\s+fatos\s+marcantes|fatos\s+marcantes|de\s+sua|sobre|da|do|de|em|para|com|por|noticias|notícias|carreira)\b",
        " ",
        cleaned_query,
        flags=re.IGNORECASE,
    )
    simplified = " ".join(simplified.split()).strip()

    if DDGS is not None and simplified and simplified.lower() != cleaned_query.lower():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with DDGS() as ddgs:
                    raw_items = list(ddgs.text(simplified, max_results=max_results))
                    if raw_items:
                        for item in raw_items:
                            results.append({
                                "title": item.get("title", "Sem título").strip(),
                                "url": item.get("href", item.get("url", "")).strip(),
                                "snippet": item.get("body", item.get("snippet", "")).strip(),
                            })
                        return results
        except Exception:
            pass

    # 3. Fallback via DuckDuckGo Instant Answer / Topics API
    for q_term in [cleaned_query, simplified]:
        if not q_term:
            continue
        try:
            resp = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": q_term, "format": "json", "no_html": 1},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                abstract = data.get("AbstractText") or data.get("Abstract")
                heading = data.get("Heading")
                url = data.get("AbstractURL")
                if abstract and heading:
                    results.append({
                        "title": heading,
                        "url": url or "https://duckduckgo.com",
                        "snippet": abstract,
                    })

                for topic in data.get("RelatedTopics", []):
                    if len(results) >= max_results:
                        break
                    if isinstance(topic, dict) and "Text" in topic:
                        results.append({
                            "title": topic.get("Text", "")[:60] + "...",
                            "url": topic.get("FirstURL", "https://duckduckgo.com"),
                            "snippet": topic.get("Text", ""),
                        })

                if results:
                    return results
        except Exception:
            pass

    # 4. Fallback via Wikipedia API (para entidades/biografias)
    for q_term in [simplified, cleaned_query]:
        if not q_term:
            continue
        try:
            wiki_url = f"https://pt.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(q_term)}"
            resp = requests.get(wiki_url, headers={"User-Agent": "RockAssistant/1.0"}, timeout=5)
            if resp.status_code == 200:
                wiki_data = resp.json()
                extract = wiki_data.get("extract")
                title = wiki_data.get("title")
                page_url = wiki_data.get("content_urls", {}).get("desktop", {}).get("page")
                if extract:
                    results.append({
                        "title": title or q_term,
                        "url": page_url or "https://pt.wikipedia.org",
                        "snippet": extract,
                    })
                    return results
        except Exception:
            pass

    return results


def search_web(query: str, max_results: int = 5) -> str:
    """Realiza a busca na web, extrai os principais resultados e retorna uma síntese formatada em texto.

    Args:
        query: Termo de pesquisa na web.
        max_results: Número máximo de resultados (padrão: 5).

    Returns:
        Síntese textual formatada com título, link e resumo dos resultados encontrados.
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return "Nenhum termo de busca fornecido."

    try:
        results = search_web_raw(cleaned_query, max_results=max_results)
        if not results:
            return f"Nenhum resultado encontrado para a busca: '{cleaned_query}'."

        lines = [
            f"🔍 Resultados da busca na web para: '{cleaned_query}'\n",
            "=" * 60,
        ]

        for i, item in enumerate(results, 1):
            title = item.get("title", "Sem título")
            url = item.get("url", "Sem link")
            snippet = item.get("snippet", "Sem descrição")

            lines.append(f"\n[{i}] {title}")
            lines.append(f"    🔗 Link: {url}")
            lines.append(f"    📝 Resumo: {snippet}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    except Exception as exc:
        return f"Erro ao realizar pesquisa na web para '{cleaned_query}': {exc}"


class WebSearchTool:
    """Wrapper orientado a objetos para buscas na web."""

    def __init__(self) -> None:
        self.name = "web_search"

    def search(self, query: str, max_results: int = 5) -> str:
        """Realiza a busca e retorna a síntese formatada em texto."""
        return search_web(query=query, max_results=max_results)

    def search_structured(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """Realiza a busca e retorna a lista estruturada de resultados."""
        return search_web_raw(query=query, max_results=max_results)



